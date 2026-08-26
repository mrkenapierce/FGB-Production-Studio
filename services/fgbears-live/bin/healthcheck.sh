#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
HEALTH_SAMPLE_FILE=${FFMPEG_HEALTH_SAMPLE_FILE:-/srv/fgbears-live/logs/ffmpeg-health.sample}
HEALTH_STATE_DIR=${FFMPEG_HEALTH_STATE_DIR:-/srv/fgbears-live/health}
RESTART_HISTORY_FILE=${FFMPEG_RESTART_HISTORY_FILE:-$HEALTH_STATE_DIR/restart-history}
RESTART_BREAKER_FILE=${FFMPEG_RESTART_BREAKER_FILE:-$HEALTH_STATE_DIR/restart-breaker}
LAG_STATUS_FILE=${FFMPEG_LAG_STATUS_FILE:-$HEALTH_STATE_DIR/lag-status}
LAG_WARNING_FILE=${FFMPEG_LAG_WARNING_FILE:-$HEALTH_STATE_DIR/lag-warning}
LAG_STATUS_BIN=${FFMPEG_LAG_STATUS_BIN:-/usr/local/bin/fgbears-stream-status}
LAG_SAMPLE_SECONDS=${FFMPEG_LAG_SAMPLE_SECONDS:-20}
LAG_WARN_SPEED=${FFMPEG_LAG_WARN_SPEED:-0.95}
RESTART_BUDGET=${FFMPEG_RESTART_BUDGET:-2}
RESTART_WINDOW_SECONDS=${FFMPEG_RESTART_WINDOW_SECONDS:-1800}
NEWS_REFRESH_BIN=${BEARS_NEWS_REFRESH_BIN:-/opt/fgbears-live/bin/refresh-bears-news.py}
NEWS_REFRESH_INTERVAL_SECONDS=${BEARS_NEWS_REFRESH_INTERVAL_SECONDS:-900}
NEWS_LOCAL_FEED=${BEARS_NEWS_LOCAL_FEED_FILE:-/srv/fgbears-live/runtime/fgb-bears-news.xml}
NEWS_REFRESH_STATUS=${BEARS_NEWS_REFRESH_STATUS_FILE:-/srv/fgbears-live/runtime/bears-news-refresh-status.env}
YOUTUBE_RELAY_SERVICE=${YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
AUDIO_HEALTH_INTERVAL_SECONDS=${FGB_AUDIO_HEALTH_INTERVAL_SECONDS:-900}
AUDIO_HEALTH_SAMPLE_SECONDS=${FGB_AUDIO_HEALTH_SAMPLE_SECONDS:-20}
AUDIO_HEALTH_EPOCH_FILE=${FGB_AUDIO_HEALTH_EPOCH_FILE:-$HEALTH_STATE_DIR/audio-health-epoch}
AUDIO_HEALTH_STATUS_FILE=${FGB_AUDIO_HEALTH_STATUS_FILE:-$HEALTH_STATE_DIR/audio-health-status}
AUDIO_HEALTH_WARNING_FILE=${FGB_AUDIO_HEALTH_WARNING_FILE:-$HEALTH_STATE_DIR/audio-health-warning}

mkdir -p "$HEALTH_STATE_DIR"

run_news_refresh() {
  [[ -f "$NEWS_REFRESH_BIN" ]] || return 0
  if ! runuser -u fgbears -- env \
    FGB_BEARS_NEWS_FEED_PATH="$NEWS_LOCAL_FEED" \
    FGB_BEARS_NEWS_STATUS_PATH="$NEWS_REFRESH_STATUS" \
    python3 "$NEWS_REFRESH_BIN" --interval-seconds "$NEWS_REFRESH_INTERVAL_SECONDS"; then
    logger -t fgbears-live-health "Bears news refresh failed; last good local feed remains in service."
  fi
}

guarded_restart() {
  local reason=$1 now cutoff count temporary
  now=$(date +%s)
  cutoff=$((now - RESTART_WINDOW_SECONDS))
  temporary="${RESTART_HISTORY_FILE}.partial"
  if [[ -s "$RESTART_HISTORY_FILE" ]]; then
    awk -v cutoff="$cutoff" '$1 >= cutoff { print $1 }' "$RESTART_HISTORY_FILE" > "$temporary"
  else
    : > "$temporary"
  fi
  mv -f "$temporary" "$RESTART_HISTORY_FILE"
  count=$(wc -l < "$RESTART_HISTORY_FILE")
  if (( count >= RESTART_BUDGET )); then
    printf '%s %s\n' "$now" "$reason" > "$RESTART_BREAKER_FILE"
    logger -t fgbears-live-health "Restart circuit open after ${count} recoveries in ${RESTART_WINDOW_SECONDS}s; reason=${reason}."
    return 1
  fi
  printf '%s\n' "$now" >> "$RESTART_HISTORY_FILE"
  logger -t fgbears-live-health "Restarting stalled stream; reason=${reason}; budget=$((count + 1))/${RESTART_BUDGET}."
  systemctl restart fgbears-live.service
}

# YouTube consumes a connectionless local MPEG-TS mirror. A relay failure must
# never restart or interrupt the primary encoder; reset only the relay and let it
# rejoin the continuously transmitted program at the next keyframe.
recover_youtube_relay() {
  if systemctl is-active --quiet "$YOUTUBE_RELAY_SERVICE"; then
    return 0
  fi

  logger -t fgbears-live-health "YouTube relay is inactive; resetting and restarting the isolated UDP relay without touching the primary encoder."
  systemctl reset-failed "$YOUTUBE_RELAY_SERVICE" || true
  systemctl restart "$YOUTUBE_RELAY_SERVICE" || true

  for _ in {1..20}; do
    if systemctl is-active --quiet "$YOUTUBE_RELAY_SERVICE"; then
      return 0
    fi
    sleep 0.25
  done

  logger -t fgbears-live-health "YouTube relay did not become active after isolated recovery."
  return 1
}

run_lag_check() {
  local output status reason speed temporary
  [[ -x "$LAG_STATUS_BIN" ]] || return 0
  if ! output=$(STREAM_STATUS_WARN_SPEED="$LAG_WARN_SPEED" "$LAG_STATUS_BIN" --sample-seconds "$LAG_SAMPLE_SECONDS" 2>&1); then
    logger -t fgbears-live-health "Lag sampler failed: ${output//$'\n'/; }"
    return 0
  fi

  temporary="${LAG_STATUS_FILE}.partial"
  printf '%s\n' "$output" > "$temporary"
  mv -f "$temporary" "$LAG_STATUS_FILE"

  status=$(printf '%s\n' "$output" | sed -n 's/^OVERALL_STATUS=//p' | tail -n 1)
  reason=$(printf '%s\n' "$output" | sed -n 's/^REASON=//p' | tail -n 1)
  speed=$(printf '%s\n' "$output" | sed -n 's/^INTERVAL_SPEED=//p' | tail -n 1)

  if [[ "$reason" == "ENCODER_BELOW_REALTIME" ]]; then
    printf '%s speed=%s threshold=%s\n' "$(date +%s)" "${speed:-NA}" "$LAG_WARN_SPEED" > "$LAG_WARNING_FILE"
    logger -t fgbears-live-health "Encoder lag warning: interval_speed=${speed:-NA}x threshold=${LAG_WARN_SPEED}x. Stream left running to avoid a restart loop."
  elif [[ "$status" == "OK" ]]; then
    rm -f "$LAG_WARNING_FILE"
  fi
}

run_audio_check() {
  local now last=0 output rc temporary
  [[ -x "$AUDIO_HEALTH_BIN" ]] || return 0
  now=$(date +%s)
  if [[ -s "$AUDIO_HEALTH_EPOCH_FILE" ]]; then
    last=$(cat "$AUDIO_HEALTH_EPOCH_FILE" 2>/dev/null || printf '0')
  fi
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  if (( now - last < AUDIO_HEALTH_INTERVAL_SECONDS )); then
    return 0
  fi

  if output=$("$AUDIO_HEALTH_BIN" --capture-seconds "$AUDIO_HEALTH_SAMPLE_SECONDS" 2>&1); then
    rc=0
  else
    rc=$?
  fi
  temporary="${AUDIO_HEALTH_STATUS_FILE}.partial"
  printf '%s\n' "$output" > "$temporary"
  mv -f "$temporary" "$AUDIO_HEALTH_STATUS_FILE"
  printf '%s\n' "$now" > "${AUDIO_HEALTH_EPOCH_FILE}.partial"
  mv -f "${AUDIO_HEALTH_EPOCH_FILE}.partial" "$AUDIO_HEALTH_EPOCH_FILE"

  if (( rc != 0 )); then
    printf '%s rc=%s %s\n' "$now" "$rc" "$(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)" > "$AUDIO_HEALTH_WARNING_FILE"
    logger -t fgbears-live-health "Audio quality warning: $(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)"
    return 0
  fi
  rm -f "$AUDIO_HEALTH_WARNING_FILE"
}

reconcile_social_relay() {
  local platform enabled_key service start_timer stop_timer
  local enabled=false now_hm
  platform=$1
  enabled_key=$2
  service="fgbears-${platform}-relay.service"
  start_timer="fgbears-${platform}-start.timer"
  stop_timer="fgbears-${platform}-stop.timer"
  grep -Eq "^${enabled_key}=(1|true|yes|on)$" "$ENV_FILE" && enabled=true

  if [[ "$enabled" != true ]]; then
    systemctl stop "$service" >/dev/null 2>&1 || true
    return 0
  fi

  systemctl enable --now "$start_timer" "$stop_timer" >/dev/null 2>&1 || true
  now_hm=$(TZ=America/Chicago date +%H%M)
  now_hm=$((10#$now_hm))
  if (( now_hm >= 900 && now_hm < 1700 )); then
    if ! systemctl is-active --quiet "$service"; then
      logger -t fgbears-live-health "Recovering scheduled ${platform} relay during the 09:00-17:00 Central window."
      systemctl reset-failed "$service" || true
      systemctl restart "$service"
    fi
  elif systemctl is-active --quiet "$service"; then
    logger -t fgbears-live-health "Stopping ${platform} relay outside the 09:00-17:00 Central window."
    systemctl stop "$service"
  fi
}

# News scanning is independent of encoder health. The five-minute host timer calls
# this script; the refresher itself runs only once per 15-minute epoch bucket.
run_news_refresh

[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then
  exit 0
fi

# A failed YouTube relay is isolated from the primary program clock. Recover it
# independently and continue checking encoder health in the same cycle.
recover_youtube_relay || true

if ! systemctl is-active --quiet fgbears-live.service; then
  guarded_restart "SERVICE_NOT_ACTIVE"
  exit 0
fi

# A process can remain "active" after output has stalled. Restart only when
# FFmpeg stops reporting progress. A speed below real time indicates resource
# pressure; the scheduled lag sampler records that condition but deliberately
# does not restart the encoder, which would create a viewer-visible restart loop.
if [[ ! -s "$PROGRESS_FILE" ]]; then
  guarded_restart "PROGRESS_MISSING"
  exit 0
fi
now=$(date +%s)
updated=$(stat -c %Y "$PROGRESS_FILE")
age=$((now - updated))
out_time_us=$(sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$PROGRESS_FILE" | tail -n 1)

if (( age > 90 )); then
  guarded_restart "PROGRESS_STALE_${age}S"
  rm -f "$HEALTH_SAMPLE_FILE"
  exit 0
fi

[[ -n "$out_time_us" ]] || exit 0
reconcile_social_relay x X_RELAY_ENABLED
reconcile_social_relay instagram INSTAGRAM_RELAY_ENABLED
run_lag_check
run_audio_check
printf '%s %s\n' "$now" "$out_time_us" > "${HEALTH_SAMPLE_FILE}.partial"
mv -f "${HEALTH_SAMPLE_FILE}.partial" "$HEALTH_SAMPLE_FILE"
rm -f "$RESTART_BREAKER_FILE"

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
# YouTube desired generation is host state, not stream.env state. This prevents
# stale environment values from reviving a retired destination.
YOUTUBE_GENERATION_FILE=/etc/fgbears-live/youtube-generation
YOUTUBE_CUTOVER_MARKER=/run/fgbears-youtube-v3/cutover-in-progress
YOUTUBE_V2_SERVICE=fgbears-youtube-v2.service
YOUTUBE_V3_SERVICE=fgbears-youtube-v3.service
YOUTUBE_V3_PROGRESS_FILE=/run/fgbears-youtube-v3/ffmpeg-progress.log
YOUTUBE_WARNING_FILE=${YOUTUBE_WARNING_FILE:-$HEALTH_STATE_DIR/youtube-v3-warning}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
AUDIO_HEALTH_INTERVAL_SECONDS=${FGB_AUDIO_HEALTH_INTERVAL_SECONDS:-300}
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
  logger -t fgbears-live-health "Restarting stalled shared program; reason=${reason}; budget=$((count + 1))/${RESTART_BUDGET}."
  systemctl restart fgbears-live.service
}

youtube_generation() {
  local generation=''
  if [[ -r "$YOUTUBE_GENERATION_FILE" ]]; then
    generation=$(tr -d '[:space:]' < "$YOUTUBE_GENERATION_FILE")
  fi
  case "$generation" in
    v2|v3) printf '%s\n' "$generation" ;;
    *)
      # Bootstrap only. Deployment writes an explicit marker before changing
      # either destination, so steady state never depends on inference.
      if systemctl is-active --quiet "$YOUTUBE_V3_SERVICE"; then printf 'v3\n'; else printf 'v2\n'; fi
      ;;
  esac
}

recover_youtube_destination() {
  local generation service label
  if [[ -e "$YOUTUBE_CUTOVER_MARKER" ]]; then
    logger -t fgbears-live-health "YouTube controlled cutover active; destination recovery intentionally deferred while shared-program health remains supervised."
    return 0
  fi
  generation=$(youtube_generation)
  if [[ "$generation" == v3 ]]; then
    service=$YOUTUBE_V3_SERVICE; label=V3
  else
    service=$YOUTUBE_V2_SERVICE; label=V2
  fi
  if systemctl is-active --quiet "$service"; then return 0; fi

  logger -t fgbears-live-health "YouTube ${generation} is inactive; restarting only desired destination process."
  systemctl reset-failed "$service" || true
  systemctl restart "$service" || true
  for _ in {1..20}; do
    if systemctl is-active --quiet "$service"; then
      logger -t fgbears-live-health "YOUTUBE_${label}_RECOVERY=RECOVERED service=$service"
      return 0
    fi
    sleep 0.25
  done
  logger -t fgbears-live-health "YOUTUBE_${label}_RECOVERY=FAILED service=$service"
  return 1
}

check_youtube_v3_pacing() {
  local now updated age speed pressure warning="" generation
  [[ ! -e "$YOUTUBE_CUTOVER_MARKER" ]] || return 0
  generation=$(youtube_generation)
  [[ "$generation" == v3 ]] || { rm -f "$YOUTUBE_WARNING_FILE"; return 0; }
  systemctl is-active --quiet "$YOUTUBE_V3_SERVICE" || return 0
  if [[ ! -s "$YOUTUBE_V3_PROGRESS_FILE" ]]; then
    warning="PROGRESS_MISSING"
  else
    now=$(date +%s)
    updated=$(stat -c %Y "$YOUTUBE_V3_PROGRESS_FILE" 2>/dev/null || echo 0)
    age=$((now - updated))
    speed=$(sed -n 's/^speed=\([0-9.]*\)x$/\1/p' "$YOUTUBE_V3_PROGRESS_FILE" | tail -n1)
    if (( age > 20 )); then
      warning="PROGRESS_STALE_${age}S"
    elif [[ -n "$speed" ]] && ! python3 -c 'import sys; assert float(sys.argv[1]) >= 0.98' "$speed"; then
      warning="BELOW_REALTIME_${speed}X"
    fi
  fi
  if journalctl -u "$YOUTUBE_V3_SERVICE" --since '-10 minutes' --no-pager 2>/dev/null | grep -Fq 'Circular buffer overrun'; then
    warning="${warning:+${warning}_}UDP_OVERRUN"
  fi
  pressure=$(awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){split($i,a,"=");print a[2]}}' /proc/pressure/cpu 2>/dev/null || true)
  if [[ -n "$warning" ]]; then
    printf '%s warning=%s cpu_pressure_avg10=%s\n' "$(date +%s)" "$warning" "${pressure:-NA}" > "$YOUTUBE_WARNING_FILE"
    logger -t fgbears-live-health "YouTube v3 pacing warning: $warning cpu_pressure_avg10=${pressure:-NA}. Destination left running; master and Rumble are never restarted for a YouTube pacing warning."
  else
    rm -f "$YOUTUBE_WARNING_FILE"
  fi
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
    logger -t fgbears-live-health "Encoder lag warning: interval_speed=${speed:-NA}x threshold=${LAG_WARN_SPEED}x. Stream left running to avoid restart loops."
  elif [[ "$status" == "OK" ]]; then
    rm -f "$LAG_WARNING_FILE"
  fi
}

run_audio_check() {
  local now last=0 output rc temporary
  [[ -x "$AUDIO_HEALTH_BIN" ]] || return 0
  now=$(date +%s)
  if [[ -s "$AUDIO_HEALTH_EPOCH_FILE" ]]; then last=$(cat "$AUDIO_HEALTH_EPOCH_FILE" 2>/dev/null || printf '0'); fi
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  if (( now - last < AUDIO_HEALTH_INTERVAL_SECONDS )); then return 0; fi
  if output=$("$AUDIO_HEALTH_BIN" --capture-seconds "$AUDIO_HEALTH_SAMPLE_SECONDS" 2>&1); then rc=0; else rc=$?; fi
  temporary="${AUDIO_HEALTH_STATUS_FILE}.partial"
  printf '%s\n' "$output" > "$temporary"; mv -f "$temporary" "$AUDIO_HEALTH_STATUS_FILE"
  printf '%s\n' "$now" > "${AUDIO_HEALTH_EPOCH_FILE}.partial"; mv -f "${AUDIO_HEALTH_EPOCH_FILE}.partial" "$AUDIO_HEALTH_EPOCH_FILE"
  if (( rc != 0 )); then
    printf '%s rc=%s %s\n' "$now" "$rc" "$(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)" > "$AUDIO_HEALTH_WARNING_FILE"
    logger -t fgbears-live-health "Audio quality warning: $(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)"
    return 0
  fi
  rm -f "$AUDIO_HEALTH_WARNING_FILE"
}

run_news_refresh
[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then exit 0; fi

# Only destination recovery changes with the YouTube generation. Master, news,
# crawl-independent lag sampling, and audio health remain continuously active.
recover_youtube_destination || true
check_youtube_v3_pacing

if ! systemctl is-active --quiet fgbears-live.service; then
  guarded_restart "SERVICE_NOT_ACTIVE"
  exit 0
fi
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
run_lag_check
run_audio_check
printf '%s %s\n' "$now" "$out_time_us" > "${HEALTH_SAMPLE_FILE}.partial"
mv -f "${HEALTH_SAMPLE_FILE}.partial" "$HEALTH_SAMPLE_FILE"
rm -f "$RESTART_BREAKER_FILE"

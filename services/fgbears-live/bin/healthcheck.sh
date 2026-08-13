#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
HEALTH_SAMPLE_FILE=${FFMPEG_HEALTH_SAMPLE_FILE:-/srv/fgbears-live/logs/ffmpeg-health.sample}
HEALTH_STATE_DIR=${FFMPEG_HEALTH_STATE_DIR:-/srv/fgbears-live/health}
RESTART_HISTORY_FILE=${FFMPEG_RESTART_HISTORY_FILE:-$HEALTH_STATE_DIR/restart-history}
RESTART_BREAKER_FILE=${FFMPEG_RESTART_BREAKER_FILE:-$HEALTH_STATE_DIR/restart-breaker}
RESTART_BUDGET=${FFMPEG_RESTART_BUDGET:-2}
RESTART_WINDOW_SECONDS=${FFMPEG_RESTART_WINDOW_SECONDS:-1800}

mkdir -p "$HEALTH_STATE_DIR"

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

[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then
  exit 0
fi

if ! systemctl is-active --quiet fgbears-live.service; then
  guarded_restart "SERVICE_NOT_ACTIVE"
  exit 0
fi

# A process can remain "active" after output has stalled. Restart only when
# FFmpeg stops reporting progress. A speed below real time indicates resource
# pressure; restarting the same encoder cannot correct it and creates a viewer-
# visible restart loop.
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
printf '%s %s\n' "$now" "$out_time_us" > "${HEALTH_SAMPLE_FILE}.partial"
mv -f "${HEALTH_SAMPLE_FILE}.partial" "$HEALTH_SAMPLE_FILE"
rm -f "$RESTART_BREAKER_FILE"

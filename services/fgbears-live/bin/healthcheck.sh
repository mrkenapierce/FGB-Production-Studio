#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
HEALTH_SAMPLE_FILE=${FFMPEG_HEALTH_SAMPLE_FILE:-/srv/fgbears-live/logs/ffmpeg-health.sample}

[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then
  exit 0
fi

if ! systemctl is-active --quiet fgbears-live.service; then
  systemctl restart fgbears-live.service
  exit 0
fi

# A process can remain "active" while producing frames too slowly. Treat a
# stale progress report or sustained real-time slowdown as unhealthy and
# recover. Compare media progress between timer runs instead of trusting
# FFmpeg's lifetime average, which is intentionally low during startup.
[[ -s "$PROGRESS_FILE" ]] || exit 0
now=$(date +%s)
updated=$(stat -c %Y "$PROGRESS_FILE")
age=$((now - updated))
out_time_us=$(sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$PROGRESS_FILE" | tail -n 1)

if (( age > 90 )); then
  logger -t fgbears-live-health "Encoder progress is ${age}s stale; restarting stream."
  systemctl restart fgbears-live.service
  rm -f "$HEALTH_SAMPLE_FILE"
  exit 0
fi

[[ -n "$out_time_us" ]] || exit 0
if [[ -s "$HEALTH_SAMPLE_FILE" ]]; then
  read -r previous_epoch previous_out_time_us < "$HEALTH_SAMPLE_FILE" || true
else
  previous_epoch=""
  previous_out_time_us=""
fi
printf '%s %s\n' "$now" "$out_time_us" > "${HEALTH_SAMPLE_FILE}.partial"
mv -f "${HEALTH_SAMPLE_FILE}.partial" "$HEALTH_SAMPLE_FILE"

# A lower media timestamp means the service restarted since the prior sample;
# use this run as the new baseline rather than causing another restart.
if [[ -z "$previous_epoch" || -z "$previous_out_time_us" ]] ||
   (( now <= previous_epoch || out_time_us <= previous_out_time_us )); then
  exit 0
fi

wall_delta=$((now - previous_epoch))
media_delta_us=$((out_time_us - previous_out_time_us))
instant_speed=$(awk -v media="$media_delta_us" -v wall="$wall_delta" 'BEGIN { printf "%.3f", media / 1000000 / wall }')
if ! awk -v value="$instant_speed" 'BEGIN { exit !(value >= 0.98) }'; then
  logger -t fgbears-live-health "Encoder interval speed is ${instant_speed}x; restarting stream."
  systemctl restart fgbears-live.service
  rm -f "$HEALTH_SAMPLE_FILE"
fi

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

# A process can remain "active" after output has stalled. Restart only when
# FFmpeg stops reporting progress. A speed below real time indicates resource
# pressure; restarting the same encoder cannot correct it and creates a viewer-
# visible restart loop.
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
printf '%s %s\n' "$now" "$out_time_us" > "${HEALTH_SAMPLE_FILE}.partial"
mv -f "${HEALTH_SAMPLE_FILE}.partial" "$HEALTH_SAMPLE_FILE"

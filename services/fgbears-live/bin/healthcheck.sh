#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}

[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then
  exit 0
fi

if ! systemctl is-active --quiet fgbears-live.service; then
  systemctl restart fgbears-live.service
  exit 0
fi

# A process can remain "active" while producing frames too slowly. Treat a
# stale progress report or severe real-time slowdown as unhealthy and recover.
[[ -s "$PROGRESS_FILE" ]] || exit 0
now=$(date +%s)
updated=$(stat -c %Y "$PROGRESS_FILE")
age=$((now - updated))
speed=$(sed -n 's/^speed=\([0-9.]*\)x$/\1/p' "$PROGRESS_FILE" | tail -n 1)

if (( age > 90 )); then
  logger -t fgbears-live-health "Encoder progress is ${age}s stale; restarting stream."
  systemctl restart fgbears-live.service
elif [[ -n "$speed" ]] && ! awk -v value="$speed" 'BEGIN { exit !(value >= 0.90) }'; then
  logger -t fgbears-live-health "Encoder speed is ${speed}x; restarting stream."
  systemctl restart fgbears-live.service
fi


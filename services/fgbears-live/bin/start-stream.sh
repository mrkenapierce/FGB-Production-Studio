#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${PLAYLIST_FILE:=/srv/fgbears-live/playlist.ffconcat}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${AD_OVERLAY_PORT:=8787}"
: "${AD_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/ad-overlay.py}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ -s "$PLAYLIST_FILE" ]] || { echo "Playlist is missing or empty: $PLAYLIST_FILE" >&2; exit 66; }
[[ -r "$AD_OVERLAY_SCRIPT" ]] || { echo "Ad overlay renderer is missing: $AD_OVERLAY_SCRIPT" >&2; exit 66; }

python3 "$AD_OVERLAY_SCRIPT" &
OVERLAY_PID=$!

cleanup() {
  if kill -0 "$OVERLAY_PID" 2>/dev/null; then
    kill "$OVERLAY_PID" 2>/dev/null || true
    wait "$OVERLAY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null; then
    break
  fi
  if ! kill -0 "$OVERLAY_PID" 2>/dev/null; then
    echo "Ad overlay renderer exited before becoming healthy." >&2
    exit 70
  fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null || {
  echo "Ad overlay renderer did not become healthy." >&2
  exit 70
}

# Dynamic advertising requires video compositing, so video is re-encoded while
# the already-normalized AAC audio remains a direct stream copy. The 640x240
# ad panel is placed in the middle-right third of the standardized 1280x720 feed.
ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -thread_queue_size 64 -f mpjpeg -i "http://127.0.0.1:${AD_OVERLAY_PORT}/overlay.mjpg" \
  -filter_complex "[0:v][1:v]overlay=x=W-w:y=H/3:eof_action=repeat:shortest=0,format=yuv420p[v]" \
  -map "[v]" -map 0:a:0 \
  -c:v libx264 -preset superfast -tune zerolatency -profile:v high \
  -b:v 4000k -maxrate 4500k -bufsize 8000k \
  -g 60 -keyint_min 60 -sc_threshold 0 -r 30 -threads 2 \
  -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

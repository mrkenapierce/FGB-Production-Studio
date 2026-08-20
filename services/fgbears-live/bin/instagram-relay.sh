#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${INSTAGRAM_RELAY_ENABLED:=0}"
: "${INSTAGRAM_LOCAL_UDP_URL:=udp://127.0.0.1:1938?pkt_size=1316}"
: "${INSTAGRAM_STREAM_URL:=}"
: "${INSTAGRAM_STREAM_KEY:=}"
: "${FFMPEG_LOGLEVEL:=warning}"

case "${INSTAGRAM_RELAY_ENABLED,,}" in
  1|true|yes|on) ;;
  *) echo "Instagram relay is disabled." >&2; exit 78 ;;
esac
[[ "$INSTAGRAM_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "Instagram local URL must remain loopback." >&2; exit 78; }
[[ "$INSTAGRAM_STREAM_URL" == rtmp://* || "$INSTAGRAM_STREAM_URL" == rtmps://* ]] || { echo "Invalid Instagram stream URL." >&2; exit 78; }
[[ -n "$INSTAGRAM_STREAM_KEY" ]] || { echo "Instagram stream key is required." >&2; exit 78; }
[[ "$INSTAGRAM_STREAM_URL$INSTAGRAM_STREAM_KEY" != *"|"* ]] || { echo "Unsupported Instagram credential character." >&2; exit 78; }

UPSTREAM_TARGET="${INSTAGRAM_STREAM_URL%/}/${INSTAGRAM_STREAM_KEY}"
exec ffmpeg -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -i "$INSTAGRAM_LOCAL_UDP_URL" \
  -map 0:v:0 -map 0:a:0 \
  -vf "scale=720:-2:flags=lanczos,pad=720:1280:0:(oh-ih)/2:black,format=yuv420p" \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -b:v 3500k -maxrate 4000k -bufsize 7000k -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -c:a aac -b:a 128k -ar 48000 -ac 2 \
  -f flv -flvflags no_duration_filesize "$UPSTREAM_TARGET"

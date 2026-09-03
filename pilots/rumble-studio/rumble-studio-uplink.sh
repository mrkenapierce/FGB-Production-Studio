#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${RUMBLE_STUDIO_STREAM_KEY:?RUMBLE_STUDIO_STREAM_KEY is required}"
: "${RUMBLE_STUDIO_RTMP_BASE:=rtmp://studio-rtmp.rumble.com/live}"
: "${RUMBLE_STUDIO_LOCAL_UDP_URL:=udp://127.0.0.1:1942?pkt_size=1316}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$RUMBLE_STUDIO_RTMP_BASE" == "rtmp://studio-rtmp.rumble.com/live" ]] || {
  echo "RUMBLE_STUDIO_RTMP_BASE must remain the approved Studio ingest URL." >&2
  exit 78
}
[[ "$RUMBLE_STUDIO_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "RUMBLE_STUDIO_LOCAL_UDP_URL must remain loopback-only." >&2
  exit 78
}
[[ "$RUMBLE_STUDIO_STREAM_KEY" != *$'\n'* && "$RUMBLE_STUDIO_STREAM_KEY" != *$'\r'* ]] || {
  echo "RUMBLE_STUDIO_STREAM_KEY must be a single line." >&2
  exit 78
}

LOCAL_BASE=${RUMBLE_STUDIO_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
STUDIO_TARGET="${RUMBLE_STUDIO_RTMP_BASE%/}/${RUMBLE_STUDIO_STREAM_KEY}"

# Dedicated Studio path: remux the already encoded master only. No video or
# audio encoder is allowed in this process. Failure here cannot stop the
# canonical direct-Rumble relay or the current YouTube-v3 safety path.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$STUDIO_TARGET"

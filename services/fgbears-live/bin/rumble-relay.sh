#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${RUMBLE_STREAM_KEY:?RUMBLE_STREAM_KEY is required}"
: "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"
: "${RUMBLE_UPSTREAM_RTMP_BASE:=rtmp://rtmp.rumble.com/live}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$RUMBLE_STREAM_KEY" != "REPLACE_WITH_RUMBLE_STREAM_KEY" ]] || {
  echo "Replace the placeholder Rumble stream key in $ENV_FILE" >&2
  exit 78
}
[[ "$RUMBLE_STREAM_KEY" != *$'\n'* && "$RUMBLE_STREAM_KEY" != *$'\r'* ]] || {
  echo "RUMBLE_STREAM_KEY must be a single line." >&2
  exit 78
}
[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "RUMBLE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
[[ "$RUMBLE_UPSTREAM_RTMP_BASE" == "rtmp://rtmp.rumble.com/live" ]] || {
  echo "RUMBLE_UPSTREAM_RTMP_BASE must remain the approved Rumble ingest URL." >&2
  exit 78
}

LOCAL_BASE=${RUMBLE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${RUMBLE_UPSTREAM_RTMP_BASE%/}/${RUMBLE_STREAM_KEY}"

# Copy/remux the already encoded program. Rumble never shares YouTube's relay
# process and cannot change the primary video or audio encoding settings.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

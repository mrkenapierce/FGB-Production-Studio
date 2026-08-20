#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${FACEBOOK_RELAY_ENABLED:=0}"
: "${FACEBOOK_LOCAL_UDP_URL:=udp://127.0.0.1:1936?pkt_size=1316}"
: "${FACEBOOK_RTMP_BASE:=rtmps://live-api-s.facebook.com:443/rtmp/}"
: "${FACEBOOK_STREAM_KEY:=}"
: "${FFMPEG_LOGLEVEL:=warning}"

case "${FACEBOOK_RELAY_ENABLED,,}" in
  1|true|yes|on) ;;
  *) echo "Facebook relay is disabled." >&2; exit 78 ;;
esac

[[ "$FACEBOOK_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "FACEBOOK_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
[[ "$FACEBOOK_RTMP_BASE" == rtmp://* || "$FACEBOOK_RTMP_BASE" == rtmps://* ]] || {
  echo "FACEBOOK_RTMP_BASE must be an RTMP or RTMPS URL." >&2
  exit 78
}
[[ -n "$FACEBOOK_STREAM_KEY" ]] || {
  echo "FACEBOOK_STREAM_KEY is required when the Facebook relay is enabled." >&2
  exit 78
}
[[ "$FACEBOOK_RTMP_BASE$FACEBOOK_STREAM_KEY" != *"|"* ]] || {
  echo "Facebook RTMP URL/key contains an unsupported tee delimiter." >&2
  exit 78
}

UPSTREAM_TARGET="${FACEBOOK_RTMP_BASE%/}/${FACEBOOK_STREAM_KEY}"

# The primary encoder continuously mirrors its already-encoded H.264/AAC program
# to loopback UDP. This sidecar is the only process that knows the Meta endpoint
# or stream key. Starting/stopping it therefore cannot interrupt YouTube or X.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -i "$FACEBOOK_LOCAL_UDP_URL" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

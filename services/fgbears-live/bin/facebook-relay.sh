#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${FACEBOOK_RELAY_ENABLED:=0}"
: "${FACEBOOK_LOCAL_UDP_URL:=udp://127.0.0.1:1944?pkt_size=1316}"
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
[[ "$FACEBOOK_RTMP_BASE" =~ ^rtmps://live-api-s\.facebook\.com(:443)?/rtmp/?$ ]] || {
  echo "FACEBOOK_RTMP_BASE must remain the approved Facebook Live RTMPS endpoint." >&2
  exit 78
}
[[ -n "$FACEBOOK_STREAM_KEY" ]] || {
  echo "FACEBOOK_STREAM_KEY is required when the Facebook relay is enabled." >&2
  exit 78
}
[[ "$FACEBOOK_STREAM_KEY" != *$'\n'* && "$FACEBOOK_STREAM_KEY" != *$'\r'* ]] || {
  echo "FACEBOOK_STREAM_KEY must be a single line." >&2
  exit 78
}
[[ "$FACEBOOK_STREAM_KEY" != *"|"* ]] || {
  echo "FACEBOOK_STREAM_KEY contains an unsupported tee delimiter." >&2
  exit 78
}

LOCAL_BASE=${FACEBOOK_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${FACEBOOK_RTMP_BASE%/}/${FACEBOOK_STREAM_KEY}"

# This process receives an already-encoded H.264/AAC localhost mirror and only
# copy/remuxes it to Facebook. It has no dependency capable of restarting the
# master program or the YouTube relay.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts+discardcorrupt -err_detect ignore_err \
  -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -rw_timeout 15000000 \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${FACEBOOK_RELAY_ENABLED:=0}"
: "${FACEBOOK_LIVE_API_ENABLED:=0}"
: "${FACEBOOK_LOCAL_UDP_URL:=udp://127.0.0.1:1944?pkt_size=1316}"
: "${FACEBOOK_DYNAMIC_TARGET_FILE:=/srv/fgbears-live/runtime/facebook-secure-stream-url}"
: "${FACEBOOK_RTMP_BASE:=rtmps://live-api-s.facebook.com:443/rtmp/}"
: "${FACEBOOK_STREAM_KEY:=}"
: "${FFMPEG_LOGLEVEL:=warning}"

truthy() {
  case "${1,,}" in 1|true|yes|on) return 0 ;; *) return 1 ;; esac
}

truthy "$FACEBOOK_RELAY_ENABLED" || { echo "Facebook relay is disabled." >&2; exit 78; }

[[ "$FACEBOOK_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "FACEBOOK_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}

LOCAL_BASE=${FACEBOOK_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"

if truthy "$FACEBOOK_LIVE_API_ENABLED"; then
  [[ -r "$FACEBOOK_DYNAMIC_TARGET_FILE" ]] || {
    echo "Meta Live API target is missing: $FACEBOOK_DYNAMIC_TARGET_FILE" >&2
    exit 78
  }
  IFS= read -r UPSTREAM_TARGET < "$FACEBOOK_DYNAMIC_TARGET_FILE"
  [[ "$UPSTREAM_TARGET" =~ ^rtmps:// ]] || {
    echo "Meta Live API target must be an RTMPS URL." >&2
    exit 78
  }
  [[ "$UPSTREAM_TARGET" != *$'\n'* && "$UPSTREAM_TARGET" != *$'\r'* && "$UPSTREAM_TARGET" != *"|"* ]] || {
    echo "Meta Live API target is malformed." >&2
    exit 78
  }
else
  [[ "$FACEBOOK_RTMP_BASE" =~ ^rtmps://live-api-s\.facebook\.com(:443)?/rtmp/?$ ]] || {
    echo "FACEBOOK_RTMP_BASE must remain the approved Facebook Live RTMPS endpoint." >&2
    exit 78
  }
  [[ -n "$FACEBOOK_STREAM_KEY" ]] || {
    echo "FACEBOOK_STREAM_KEY is required when Meta Live API mode is disabled." >&2
    exit 78
  }
  [[ "$FACEBOOK_STREAM_KEY" != *$'\n'* && "$FACEBOOK_STREAM_KEY" != *$'\r'* && "$FACEBOOK_STREAM_KEY" != *"|"* ]] || {
    echo "FACEBOOK_STREAM_KEY must be one line and cannot contain |." >&2
    exit 78
  }
  UPSTREAM_TARGET="${FACEBOOK_RTMP_BASE%/}/${FACEBOOK_STREAM_KEY}"
fi

# This process receives an already-encoded H.264/AAC localhost mirror and only
# copy/remuxes it to Facebook. In Meta Live API mode, the target URL is created
# immediately before each public LiveVideo and is never placed in process args
# of the master program or YouTube relay.
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

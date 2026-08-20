#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_RTMP_BASE:=rtmp://127.0.0.1:1935/live}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FACEBOOK_RELAY_ENABLED:=0}"
: "${FACEBOOK_LOCAL_RTMP_BASE:=rtmp://127.0.0.1:1936/live}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${TEE_FIFO_OPTIONS:=attempt_recovery=1:recover_any_error=1:recovery_wait_time=5}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ "$YOUTUBE_LOCAL_RTMP_BASE" == rtmp://127.0.0.1:* ]] || {
  echo "YOUTUBE_LOCAL_RTMP_BASE must remain a loopback RTMP URL." >&2
  exit 78
}
[[ "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmp://* || "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmps://* ]] || {
  echo "YOUTUBE_UPSTREAM_RTMP_BASE must be an RTMP or RTMPS URL." >&2
  exit 78
}
[[ "$FACEBOOK_LOCAL_RTMP_BASE" == rtmp://127.0.0.1:* ]] || {
  echo "FACEBOOK_LOCAL_RTMP_BASE must remain a loopback RTMP URL." >&2
  exit 78
}

case "${FACEBOOK_RELAY_ENABLED,,}" in
  1|true|yes|on) FACEBOOK_RELAY_ACTIVE=1 ;;
  0|false|no|off|"") FACEBOOK_RELAY_ACTIVE=0 ;;
  *)
    echo "FACEBOOK_RELAY_ENABLED must be 0/1, false/true, no/yes, or off/on." >&2
    exit 64
    ;;
esac

LOCAL_TARGET="${YOUTUBE_LOCAL_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

if (( FACEBOOK_RELAY_ACTIVE )); then
  FACEBOOK_LOCAL_TARGET="${FACEBOOK_LOCAL_RTMP_BASE%/}/fgb-facebook"
  TEE_TARGETS="[f=flv:flvflags=no_duration_filesize:onfail=ignore]${UPSTREAM_TARGET}|[f=flv:flvflags=no_duration_filesize:onfail=ignore]${FACEBOOK_LOCAL_TARGET}"

  # The relay receives the primary H.264/AAC program once and copy-remuxes it.
  # Facebook receives only a loopback copy. If its sidecar disappears, the FIFO
  # retries localhost while the YouTube output continues independently.
  exec ffmpeg \
    -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
    -listen 1 -i "$LOCAL_TARGET" \
    -map 0:v:0 -map 0:a:0 \
    -c copy \
    -f tee -use_fifo 1 -fifo_options "$TEE_FIFO_OPTIONS" \
    "$TEE_TARGETS"
fi

# Facebook disabled: preserve the simplest possible YouTube-only copy-remux path.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -listen 1 -i "$LOCAL_TARGET" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

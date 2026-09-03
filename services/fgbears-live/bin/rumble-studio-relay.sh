#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${RUMBLE_STREAM_KEY:?RUMBLE_STREAM_KEY is required}"
: "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"
: "${RUMBLE_UPSTREAM_RTMP_BASE:=rtmp://rtmp.rumble.com/live}"
: "${RUMBLE_STUDIO_ENABLE:=0}"
: "${RUMBLE_STUDIO_RTMP_BASE:=}"
: "${RUMBLE_STUDIO_STREAM_KEY:=}"
: "${RUMBLE_STUDIO_MODE:=shadow}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$RUMBLE_STREAM_KEY" != "REPLACE_WITH_RUMBLE_STREAM_KEY" ]] || {
  echo "Replace the placeholder Rumble stream key in $ENV_FILE" >&2
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
[[ "$RUMBLE_STUDIO_ENABLE" == 0 || "$RUMBLE_STUDIO_ENABLE" == 1 ]] || {
  echo "RUMBLE_STUDIO_ENABLE must be 0 or 1." >&2
  exit 78
}
[[ "$RUMBLE_STUDIO_MODE" == shadow || "$RUMBLE_STUDIO_MODE" == studio-only ]] || {
  echo "RUMBLE_STUDIO_MODE must be shadow or studio-only." >&2
  exit 78
}

LOCAL_BASE=${RUMBLE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
RUMBLE_TARGET="${RUMBLE_UPSTREAM_RTMP_BASE%/}/${RUMBLE_STREAM_KEY}"

if [[ "$RUMBLE_STUDIO_ENABLE" == 0 ]]; then
  exec ffmpeg \
    -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
    -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
    -i "$LOCAL_INPUT" \
    -map 0:v:0 -map 0:a:0 -c copy \
    -f flv -flvflags no_duration_filesize \
    "$RUMBLE_TARGET"
fi

[[ -n "$RUMBLE_STUDIO_RTMP_BASE" && -n "$RUMBLE_STUDIO_STREAM_KEY" ]] || {
  echo "Rumble Studio pilot enabled but Direct RTMP credentials are missing." >&2
  exit 78
}
[[ "$RUMBLE_STUDIO_RTMP_BASE" == rtmp://* || "$RUMBLE_STUDIO_RTMP_BASE" == rtmps://* ]] || {
  echo "RUMBLE_STUDIO_RTMP_BASE must be RTMP or RTMPS." >&2
  exit 78
}
[[ "$RUMBLE_STUDIO_STREAM_KEY" != *$'\n'* && "$RUMBLE_STUDIO_STREAM_KEY" != *$'\r'* ]] || {
  echo "RUMBLE_STUDIO_STREAM_KEY must be a single line." >&2
  exit 78
}

STUDIO_TARGET="${RUMBLE_STUDIO_RTMP_BASE%/}/${RUMBLE_STUDIO_STREAM_KEY}"

if [[ "$RUMBLE_STUDIO_MODE" == studio-only ]]; then
  # Reversible cutover: Studio becomes the Rumble + YouTube distributor while
  # the shared master and legacy YouTube-v3 safety path remain untouched.
  exec ffmpeg \
    -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
    -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
    -i "$LOCAL_INPUT" \
    -map 0:v:0 -map 0:a:0 -c copy \
    -f flv -flvflags no_duration_filesize \
    "$STUDIO_TARGET"
fi

TEE_FIFO_OPTIONS='attempt_recovery=1:recover_any_error=1:recovery_wait_time=5'
TEE_TARGETS="[f=flv:flvflags=no_duration_filesize:onfail=ignore]${RUMBLE_TARGET}|[f=flv:flvflags=no_duration_filesize:onfail=ignore]${STUDIO_TARGET}"

# Shadow pilot: one decode-free input, two copy/remux outputs. Rumble direct stays
# canonical while Studio is evaluated. No video or audio re-encode occurs here.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 -c copy \
  -f tee -use_fifo 1 -fifo_options "$TEE_FIFO_OPTIONS" \
  "$TEE_TARGETS"

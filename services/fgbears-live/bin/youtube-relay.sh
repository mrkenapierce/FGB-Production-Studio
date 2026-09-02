#!/usr/bin/env bash
# Canonical YouTube transport for FGBears Live.
#
# Production invariant: this service must never decode, re-encode, re-clock,
# parse/remux through GStreamer, or insert platform-specific video. It consumes
# the exact MPEG-TS mirror emitted by the shared master and copy-remuxes both
# H.264 video and AAC audio directly to YouTube RTMPS. Keeping this path boring
# is intentional: Rumble receives the sibling copy of the same master program,
# so any YouTube-only DSP/router/compositor is a regression risk.
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "YOUTUBE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
[[ "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmp://* || "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmps://* ]] || {
  echo "YOUTUBE_UPSTREAM_RTMP_BASE must be an RTMP or RTMPS URL." >&2
  exit 78
}

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

echo "Starting canonical YouTube copy-remux relay; video/audio bitstreams remain untouched." >&2
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

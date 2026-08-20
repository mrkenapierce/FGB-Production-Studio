#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_RTMP_BASE:=rtmp://127.0.0.1:1935/live}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"

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

LOCAL_TARGET="${YOUTUBE_LOCAL_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

# Dedicated YouTube copy-remux path. Facebook is deliberately absent here so a
# Facebook change cannot alter, restart, or invalidate the YouTube muxer.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -listen 1 -i "$LOCAL_TARGET" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

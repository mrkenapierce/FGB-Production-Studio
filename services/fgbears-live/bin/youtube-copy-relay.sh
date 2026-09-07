#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_COPY_LOCAL_UDP_URL:=udp://127.0.0.1:1942?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ "$YOUTUBE_STREAM_KEY" != *$'\n'* && "$YOUTUBE_STREAM_KEY" != *$'\r'* ]] || {
  echo "YOUTUBE_STREAM_KEY must be a single line." >&2
  exit 78
}
[[ "$YOUTUBE_COPY_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "YOUTUBE_COPY_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
# YouTube can assign different RTMPS ingest hosts. Accept only TLS endpoints
# under rtmps.youtube.com, optionally with YouTube's documented port 443, and
# keep the live2 application path fixed.
[[ "$YOUTUBE_UPSTREAM_RTMP_BASE" =~ ^rtmps://([a-z0-9-]+\.)?rtmps\.youtube\.com(:443)?/live2$ ]] || {
  echo "YOUTUBE_UPSTREAM_RTMP_BASE must be an approved YouTube RTMPS ingest URL." >&2
  exit 78
}

LOCAL_BASE=${YOUTUBE_COPY_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

# Copy/remux only. The encoded program received by Rumble is mirrored to this
# loopback input, then sent to YouTube without video decoding, filters, scaling,
# audio processing, or re-encoding.
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

#!/usr/bin/env bash
set -Eeuo pipefail
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || exit 78
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_COPY_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"
[[ "$YOUTUBE_COPY_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78
[[ "$YOUTUBE_UPSTREAM_RTMP_BASE" =~ ^rtmps://([a-z0-9-]+\.)?rtmps\.youtube\.com(:443)?/live2$ ]] || exit 78
LOCAL_BASE=${YOUTUBE_COPY_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
# Emergency direct stream-copy path. No tee muxer and no Facebook output.
# MPEG-TS carries H.264 with codec tag 27 (0x1b); FLV expects tag 7. Reset the
# output video codec tag explicitly while preserving the encoded H.264 packets.
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts+discardcorrupt -err_detect ignore_err \
  -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy -tag:v 7 \
  -rw_timeout 15000000 \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

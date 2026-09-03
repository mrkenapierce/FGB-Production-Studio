#!/usr/bin/env bash
set -Eeuo pipefail

# Minimal YouTube branch:
#   shared master UDP -> exact-box overlay -> one x264 encode -> YouTube RTMPS
# Audio is copied unchanged from the mastered source.

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
OVERLAY=/opt/fgbears-live/bin/youtube-overlay-stream.py

[[ -x "$OVERLAY" ]] || { echo "Missing overlay producer: $OVERLAY" >&2; exit 78; }

# There is deliberately no tee, monitor file, FIFO muxer, audio filter, audio
# encoder, routing daemon, or fallback relay here. If FFmpeg exits, systemd
# restarts this one YouTube service and establishes a fresh ingest connection.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt \
  -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size 512 -i "$LOCAL_INPUT" \
  -thread_queue_size 8 \
  -f rawvideo -pixel_format rgba -video_size 798x470 -framerate 10 \
  -i <("$OVERLAY") \
  -filter_complex '[0:v:0]setsar=1[base];[base][1:v:0]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v]' \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v 3500k -maxrate 4000k -bufsize 7000k \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a copy \
  -rw_timeout 10000000 \
  -f flv -flvflags no_duration_filesize \
  "$TARGET"

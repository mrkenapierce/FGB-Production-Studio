#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"

[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "YouTube input must be loopback UDP" >&2; exit 78; }

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=2000000&overrun_nonfatal=1&reuse=1"
TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
OVERLAY=/opt/fgbears-live/youtube-v2/youtube-v2-overlay.py

[[ -x "$OVERLAY" ]] || { echo "Missing YouTube v2 overlay renderer: $OVERLAY" >&2; exit 78; }

# Rebuild both clocks from decoded frame/sample counts. This prevents source
# concat discontinuities or copied audio timestamps from reaching YouTube.
# The master program itself is not altered and Rumble continues on its separate
# loopback feed at port 1940.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt \
  -err_detect ignore_err \
  -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size 2048 -i "$LOCAL_INPUT" \
  -thread_queue_size 128 \
  -f rawvideo -pixel_format rgba -video_size 798x470 -framerate 10 \
  -i <("$OVERLAY") \
  -filter_complex \
    '[0:v:0]fps=30:start_time=0,settb=AVTB,setpts=N/(30*TB),setsar=1[base];\
     [1:v:0]settb=AVTB,setpts=N/(10*TB)[cover];\
     [base][cover]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v];\
     [0:a:0]aresample=44100:async=1000:first_pts=0,asetpts=N/SR/TB[a]' \
  -map '[v]' -map '[a]' \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r 30 -fps_mode cfr -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v 3500k -maxrate 4000k -bufsize 7000k \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a 128k -ar 44100 -ac 2 \
  -max_muxing_queue_size 2048 \
  -rw_timeout 15000000 \
  -f flv -flvflags no_duration_filesize \
  "$TARGET"

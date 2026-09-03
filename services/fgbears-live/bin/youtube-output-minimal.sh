#!/usr/bin/env bash
set -Eeuo pipefail

# Minimal YouTube branch:
#   shared master UDP -> timestamp normalization -> exact-box overlay
#   -> one x264 video encode + one AAC audio encode -> YouTube RTMPS
# There is exactly one YouTube owner and no router/watchdog/fallback relay.

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=2000000&overrun_nonfatal=1&reuse=1"
TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
OVERLAY=/opt/fgbears-live/bin/youtube-overlay-stream.py

[[ -x "$OVERLAY" ]] || { echo "Missing overlay producer: $OVERLAY" >&2; exit 78; }

# The local MPEG-TS feed can be joined mid-GOP and can inherit timestamp jumps
# when the looping media source crosses file boundaries. Do not forward those
# source timestamps to YouTube. Rebuild a continuous 30-fps video clock and a
# continuous 44.1-kHz audio clock inside this one output process. Corrupt or
# incomplete input packets are discarded; the next keyframe/header refresh
# restores video decode without introducing a second transport owner.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt \
  -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size 2048 -i "$LOCAL_INPUT" \
  -thread_queue_size 128 \
  -f rawvideo -pixel_format rgba -video_size 798x470 -framerate 10 \
  -i <("$OVERLAY") \
  -filter_complex \
    '[0:v:0]fps=30,settb=AVTB,setpts=N/(30*TB),setsar=1[base];\
     [1:v:0]settb=AVTB,setpts=N/(10*TB)[ov];\
     [base][ov]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v];\
     [0:a:0]aresample=44100:async=1:first_pts=0,asetpts=N/SR/TB[a]' \
  -map '[v]' -map '[a]' \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r 30 -fps_mode cfr -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v 3500k -maxrate 4000k -bufsize 7000k \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a 128k -ar 44100 -ac 2 \
  -rw_timeout 10000000 \
  -f flv -flvflags no_duration_filesize \
  "$TARGET"

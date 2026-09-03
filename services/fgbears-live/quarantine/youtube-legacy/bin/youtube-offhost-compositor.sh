#!/usr/bin/env bash
set -Eeuo pipefail

# Dedicated/off-host YouTube compositor. This is intentionally NOT suitable for
# the 0.5-OCPU production Oracle source VM. It accepts the already-encoded master
# over SRT, overlays only the question-box RGBA mask, re-encodes video on this
# separate worker, copies AAC audio, and publishes to YouTube RTMPS.

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
SRT_LISTEN_PORT="${FGB_COMPOSITOR_SRT_PORT:-9000}"
MASK_PORT="${YOUTUBE_QUESTION_MASK_PORT:-8791}"
MASK_X="${YOUTUBE_QUESTION_MASK_X:-480}"
MASK_Y="${YOUTUBE_QUESTION_MASK_Y:-200}"
MASK_WIDTH="${YOUTUBE_QUESTION_MASK_WIDTH:-640}"
MASK_HEIGHT="${YOUTUBE_QUESTION_MASK_HEIGHT:-360}"
YOUTUBE_BASE="${YOUTUBE_UPSTREAM_RTMP_BASE:-rtmps://a.rtmps.youtube.com/live2}"
VIDEO_BITRATE="${FGB_COMPOSITOR_VIDEO_BITRATE:-5000k}"
VIDEO_MAXRATE="${FGB_COMPOSITOR_VIDEO_MAXRATE:-5500k}"
VIDEO_BUFSIZE="${FGB_COMPOSITOR_VIDEO_BUFSIZE:-10000k}"
X264_PRESET="${FGB_COMPOSITOR_X264_PRESET:-veryfast}"
THREADS="${FGB_COMPOSITOR_THREADS:-0}"

# Hard safety boundary: the RGBA input itself is only 640x360 by default, so it
# cannot cover the full 1280x720 picture even if every pixel in the mask becomes
# opaque. The input is anchored over the verified question/answer rectangle.
exec ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts \
  -probesize 10000000 -analyzeduration 10000000 \
  -i "srt://0.0.0.0:${SRT_LISTEN_PORT}?mode=listener&latency=200000&rcvlatency=200000&peerlatency=200000" \
  -f rawvideo -pixel_format rgba -video_size "${MASK_WIDTH}x${MASK_HEIGHT}" -framerate 30 \
  -i "http://127.0.0.1:${MASK_PORT}/overlay.rgba" \
  -filter_complex "[0:v:0][1:v:0]overlay=${MASK_X}:${MASK_Y}:format=auto:shortest=1[v]" \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset "$X264_PRESET" -tune zerolatency \
  -profile:v high -pix_fmt yuv420p -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_MAXRATE" -bufsize "$VIDEO_BUFSIZE" \
  -threads "$THREADS" \
  -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_BASE%/}/${YOUTUBE_STREAM_KEY}"

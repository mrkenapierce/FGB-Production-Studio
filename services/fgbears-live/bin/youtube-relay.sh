#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${OUTPUT_FPS:=30}"
: "${VIDEO_GOP:=60}"
: "${YOUTUBE_VIDEO_BITRATE:=5000k}"
: "${YOUTUBE_VIDEO_MAXRATE:=5500k}"
: "${YOUTUBE_VIDEO_BUFSIZE:=10000k}"
: "${YOUTUBE_TRIVIA_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/youtube-trivia-overlay.py}"
: "${YOUTUBE_TRIVIA_OVERLAY_PORT:=8790}"
: "${YOUTUBE_TRIVIA_OVERLAY_FPS:=2}"

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
# Sender options such as pkt_size are not useful to the receiving socket. Keep
# the same loopback host/port, but give the receiver a deep FIFO so short CPU or
# network stalls do not drop the local program. MPEG-TS headers and H.264 SPS/PPS
# are resent by the primary encoder at keyframes, so this process can restart and
# rejoin the live program independently.
LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

run_copy_fallback() {
  echo "YouTube trivia overlay unavailable; preserving the live stream with copy-remux fallback." >&2
  exec ffmpeg \
    -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
    -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
    -i "$LOCAL_INPUT" \
    -map 0:v:0 -map 0:a:0 \
    -c copy \
    -f flv -flvflags no_duration_filesize \
    "$UPSTREAM_TARGET"
}

if [[ ! -r "$YOUTUBE_TRIVIA_OVERLAY_SCRIPT" ]]; then
  run_copy_fallback
fi

python3 "$YOUTUBE_TRIVIA_OVERLAY_SCRIPT" &
TRIVIA_OVERLAY_PID=$!
cleanup() {
  if kill -0 "$TRIVIA_OVERLAY_PID" 2>/dev/null; then
    kill "$TRIVIA_OVERLAY_PID" 2>/dev/null || true
    wait "$TRIVIA_OVERLAY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${YOUTUBE_TRIVIA_OVERLAY_PORT}/healthz" >/dev/null; then
    break
  fi
  if ! kill -0 "$TRIVIA_OVERLAY_PID" 2>/dev/null; then
    cleanup
    trap - EXIT INT TERM
    run_copy_fallback
  fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${YOUTUBE_TRIVIA_OVERLAY_PORT}/healthz" >/dev/null || {
  cleanup
  trap - EXIT INT TERM
  run_copy_fallback
}

# systemd owns this service cgroup, so the renderer is stopped automatically if
# the FFmpeg main process exits. Replace the shell with FFmpeg so MainPID and
# socket diagnostics continue to identify the YouTube relay unambiguously.
trap - EXIT INT TERM
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -thread_queue_size 8 -f rawvideo -pixel_format rgba -video_size 1280x720 \
  -framerate "$YOUTUBE_TRIVIA_OVERLAY_FPS" \
  -i "http://127.0.0.1:${YOUTUBE_TRIVIA_OVERLAY_PORT}/overlay.rgba" \
  -filter_complex "[0:v][1:v]overlay=x=0:y=0:shortest=1:format=auto,format=yuv420p[v]" \
  -map "[v]" -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -b:v "$YOUTUBE_VIDEO_BITRATE" -maxrate "$YOUTUBE_VIDEO_MAXRATE" -bufsize "$YOUTUBE_VIDEO_BUFSIZE" \
  -g "$VIDEO_GOP" -keyint_min "$VIDEO_GOP" -sc_threshold 0 -r "$OUTPUT_FPS" -fps_mode cfr -threads 0 \
  -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

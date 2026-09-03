#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"
: "${PLAYLIST_FILE:=/srv/fgbears-live/playlist.ffconcat}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${OUTPUT_FPS:=30}"
: "${VIDEO_GOP:=60}"
: "${AD_OVERLAY_PORT:=8787}"
: "${AD_OVERLAY_FPS:=15}"
: "${AD_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/ad-overlay.py}"
: "${CRAWL_OVERLAY_PORT:=8788}"
: "${CRAWL_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/crawl-overlay-hq.py}"
: "${CRAWL_OVERLAY_FPS:=30}"
: "${BEARS_NEWS_SCRIPT:=/opt/fgbears-live/bin/bears-news-feed-hq.py}"
: "${BEARS_NEWS_OVERLAY_PORT:=8789}"
: "${BEARS_NEWS_OVERLAY_FPS:=30}"
: "${FFMPEG_PROGRESS_FILE:=/srv/fgbears-live/logs/ffmpeg-progress.log}"
: "${AD_FRAME_FILE:=/srv/fgbears-live/runtime/ad-frame.jpg}"
: "${CRAWL_RUNTIME_DIR:=/srv/fgbears-live/runtime}"

[[ -s "$PLAYLIST_FILE" ]] || { echo "Playlist is missing or empty: $PLAYLIST_FILE" >&2; exit 66; }
for script in "$AD_OVERLAY_SCRIPT" "$CRAWL_OVERLAY_SCRIPT" "$BEARS_NEWS_SCRIPT"; do
  [[ -r "$script" ]] || { echo "Overlay renderer missing: $script" >&2; exit 66; }
done
[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78
[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78

# The shared master knows nothing about platform credentials or platform
# overlays. It renders once and writes the same finished program directly to two
# loopback MPEG-TS sockets. There are no per-destination FIFO recovery queues.
TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${RUMBLE_LOCAL_UDP_URL}"

python3 "$AD_OVERLAY_SCRIPT" & AD_PID=$!
python3 "$CRAWL_OVERLAY_SCRIPT" & CRAWL_PID=$!
python3 "$BEARS_NEWS_SCRIPT" & NEWS_PID=$!
FFMPEG_PID=""

cleanup() {
  for p in "${FFMPEG_PID:-}" "$AD_PID" "$CRAWL_PID" "$NEWS_PID"; do
    [[ -n "$p" ]] || continue
    kill -INT "$p" 2>/dev/null || true
    wait "$p" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

wait_http() {
  local port=$1 pid=$2 label=$3
  for _ in $(seq 1 30); do
    curl -fsS --max-time 1 "http://127.0.0.1:${port}/healthz" >/dev/null 2>&1 && return 0
    kill -0 "$pid" 2>/dev/null || { echo "$label renderer exited" >&2; return 1; }
    sleep 0.2
  done
  echo "$label renderer did not become healthy" >&2
  return 1
}
wait_http "$AD_OVERLAY_PORT" "$AD_PID" ad
wait_http "$CRAWL_OVERLAY_PORT" "$CRAWL_PID" crawl
wait_http "$BEARS_NEWS_OVERLAY_PORT" "$NEWS_PID" news

for f in \
  "$AD_FRAME_FILE" \
  "$CRAWL_RUNTIME_DIR/crawl-label.txt" \
  "$CRAWL_RUNTIME_DIR/crawl-message.txt" \
  "$CRAWL_RUNTIME_DIR/bears-news-label.txt" \
  "$CRAWL_RUNTIME_DIR/bears-news-message.txt"; do
  [[ -e "$f" ]] || { echo "Runtime overlay file missing: $f" >&2; exit 70; }
done

progress_sink() {
  local block="" line tmp="${FFMPEG_PROGRESS_FILE}.partial"
  while IFS= read -r line; do
    block+="$line"$'\n'
    if [[ "$line" == progress=* ]]; then
      printf '%s' "$block" > "$tmp"
      mv -f "$tmp" "$FFMPEG_PROGRESS_FILE"
      block=""
    fi
  done
}

ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -progress pipe:3 -stats_period 5 \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -thread_queue_size 64 -fflags +genpts -r "$AD_OVERLAY_FPS" -f mpjpeg -i "http://127.0.0.1:${AD_OVERLAY_PORT}/overlay.mjpg" \
  -thread_queue_size 64 -fflags +genpts -r "$CRAWL_OVERLAY_FPS" -f mpjpeg -i "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/overlay.mjpg" \
  -thread_queue_size 64 -fflags +genpts -r "$BEARS_NEWS_OVERLAY_FPS" -f mpjpeg -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.mjpg" \
  -filter_complex "[1:v][3:v]overlay=x=0:y=0:shortest=1[withnews];[withnews][2:v]overlay=x=0:y=574:shortest=1,drawbox=x=0:y=0:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=713:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=0:w=7:h=720:color=0xC83803:t=fill,drawbox=x=1273:y=0:w=7:h=720:color=0xC83803:t=fill,format=yuv420p[v]" \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -b:v 5000k -maxrate 5500k -bufsize 10000k \
  -g "$VIDEO_GOP" -keyint_min "$VIDEO_GOP" -sc_threshold 0 -r "$OUTPUT_FPS" -fps_mode cfr \
  -c:a copy \
  -f tee "$TEE_TARGETS" \
  3> >(progress_sink) &
FFMPEG_PID=$!
wait "$FFMPEG_PID"

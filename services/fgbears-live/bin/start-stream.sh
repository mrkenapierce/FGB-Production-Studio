#!/usr/bin/env bash
# The cleanup handler is invoked indirectly by traps.
# shellcheck disable=SC2317
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"
: "${PLAYLIST_FILE:=/srv/fgbears-live/playlist.ffconcat}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${OUTPUT_FPS:=30}"
: "${VIDEO_GOP:=60}"
: "${AD_OVERLAY_PORT:=8787}"
: "${AD_OVERLAY_FPS:=30}"
: "${AD_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/ad-overlay.py}"
: "${CRAWL_OVERLAY_PORT:=8788}"
: "${CRAWL_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/crawl-overlay-hq.py}"
: "${CRAWL_OVERLAY_FPS:=30}"
: "${BEARS_NEWS_SCRIPT:=/opt/fgbears-live/bin/bears-news-feed.py}"
: "${BEARS_NEWS_OVERLAY_PORT:=8789}"
: "${BEARS_NEWS_OVERLAY_FPS:=30}"
: "${BEARS_NEWS_SCROLL_PPS:=58}"
: "${FFMPEG_PROGRESS_FILE:=/srv/fgbears-live/logs/ffmpeg-progress.log}"
: "${AD_FRAME_FILE:=/srv/fgbears-live/runtime/ad-frame.jpg}"
: "${CRAWL_RUNTIME_DIR:=/srv/fgbears-live/runtime}"
: "${TEE_FIFO_OPTIONS:=attempt_recovery=1:recover_any_error=1:recovery_wait_time=5}"

[[ -s "$PLAYLIST_FILE" ]] || { echo "Playlist is missing or empty: $PLAYLIST_FILE" >&2; exit 66; }
[[ -r "$AD_OVERLAY_SCRIPT" ]] || { echo "Ad overlay renderer is missing: $AD_OVERLAY_SCRIPT" >&2; exit 66; }
[[ -r "$CRAWL_OVERLAY_SCRIPT" ]] || { echo "Crawl overlay renderer is missing: $CRAWL_OVERLAY_SCRIPT" >&2; exit 66; }
[[ -r "$BEARS_NEWS_SCRIPT" ]] || { echo "Bears news renderer is missing: $BEARS_NEWS_SCRIPT" >&2; exit 66; }
[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "RUMBLE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}

TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${RUMBLE_LOCAL_UDP_URL}"
printf 'FGBears Live output: Rumble-only local UDP mirror.\n'

python3 "$AD_OVERLAY_SCRIPT" &
OVERLAY_PID=$!
python3 "$CRAWL_OVERLAY_SCRIPT" &
CRAWL_PID=$!
python3 "$BEARS_NEWS_SCRIPT" &
NEWS_PID=$!

cleanup() {
  if [[ -n "${FFMPEG_PID:-}" ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
    kill -INT "$FFMPEG_PID" 2>/dev/null || true
    wait "$FFMPEG_PID" 2>/dev/null || true
  fi
  if kill -0 "$OVERLAY_PID" 2>/dev/null; then kill "$OVERLAY_PID" 2>/dev/null || true; wait "$OVERLAY_PID" 2>/dev/null || true; fi
  if kill -0 "$CRAWL_PID" 2>/dev/null; then kill "$CRAWL_PID" 2>/dev/null || true; wait "$CRAWL_PID" 2>/dev/null || true; fi
  if kill -0 "$NEWS_PID" 2>/dev/null; then kill "$NEWS_PID" 2>/dev/null || true; wait "$NEWS_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null; then break; fi
  if ! kill -0 "$OVERLAY_PID" 2>/dev/null; then echo "Ad overlay renderer exited before becoming healthy." >&2; exit 70; fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null || { echo "Ad overlay renderer did not become healthy." >&2; exit 70; }

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/healthz" >/dev/null; then break; fi
  if ! kill -0 "$CRAWL_PID" 2>/dev/null; then echo "Crawl overlay renderer exited before becoming healthy." >&2; exit 70; fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/healthz" >/dev/null || { echo "Crawl overlay renderer did not become healthy." >&2; exit 70; }

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/healthz" >/dev/null; then break; fi
  if ! kill -0 "$NEWS_PID" 2>/dev/null; then echo "Bears news renderer exited before becoming healthy." >&2; exit 70; fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/healthz" >/dev/null || { echo "Bears news renderer did not become healthy." >&2; exit 70; }

for runtime_file in "$AD_FRAME_FILE" "$CRAWL_RUNTIME_DIR/crawl-label.txt" "$CRAWL_RUNTIME_DIR/crawl-message.txt" "$CRAWL_RUNTIME_DIR/bears-news-label.txt" "$CRAWL_RUNTIME_DIR/bears-news-message.txt"; do
  [[ -e "$runtime_file" ]] || { echo "Runtime overlay file is missing: $runtime_file" >&2; exit 70; }
done

progress_sink() {
  local block="" line temporary="${FFMPEG_PROGRESS_FILE}.partial"
  while IFS= read -r line; do
    block+="$line"$'\n'
    if [[ "$line" == progress=* ]]; then
      printf '%s' "$block" > "$temporary"
      mv -f "$temporary" "$FFMPEG_PROGRESS_FILE"
      block=""
    fi
  done
}

FFMPEG_PID=""

# The advertising renderer is the permanent 1280x720 visual source and must be
# ingested at 30 fps. Feeding that source at 15 fps forces CFR duplication and
# makes the whole broadcast timeline fall behind real time.
ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -progress pipe:3 -stats_period 5 \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -thread_queue_size 64 -fflags +genpts -r "$AD_OVERLAY_FPS" -f mpjpeg -i "http://127.0.0.1:${AD_OVERLAY_PORT}/overlay.mjpg" \
  -thread_queue_size 256 -f rawvideo -pixel_format rgba -video_size 1280x139 -framerate "$CRAWL_OVERLAY_FPS" -i "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/overlay.rgba" \
  -thread_queue_size 256 -f rawvideo -pixel_format rgba -video_size 1280x104 -framerate "$BEARS_NEWS_OVERLAY_FPS" -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.rgba" \
  -filter_complex "[1:v][3:v]overlay=x=0:y=0:shortest=1[withnews];[withnews][2:v]overlay=x=0:y=574:shortest=1,drawbox=x=0:y=0:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=713:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=0:w=7:h=720:color=0xC83803:t=fill,drawbox=x=1273:y=0:w=7:h=720:color=0xC83803:t=fill,format=yuv420p[v]" \
  -map "[v]" -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -b:v 5000k -maxrate 5500k -bufsize 10000k \
  -g "$VIDEO_GOP" -keyint_min "$VIDEO_GOP" -sc_threshold 0 -r "$OUTPUT_FPS" -fps_mode cfr -threads 0 \
  -c:a copy \
  -f tee -use_fifo 1 -fifo_options "$TEE_FIFO_OPTIONS" \
  "$TEE_TARGETS" 3> >(progress_sink) &
FFMPEG_PID=$!
set +e
wait "$FFMPEG_PID"
status=$?
set -e
exit "$status"

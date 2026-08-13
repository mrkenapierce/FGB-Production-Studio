#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${PLAYLIST_FILE:=/srv/fgbears-live/playlist.ffconcat}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${AD_OVERLAY_PORT:=8787}"
: "${AD_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/ad-overlay.py}"
: "${CRAWL_OVERLAY_PORT:=8788}"
: "${CRAWL_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/crawl-overlay.py}"
: "${CRAWL_OVERLAY_FPS:=15}"
: "${FFMPEG_PROGRESS_FILE:=/srv/fgbears-live/logs/ffmpeg-progress.log}"
: "${AD_FRAME_FILE:=/srv/fgbears-live/runtime/ad-frame.jpg}"
: "${CRAWL_RUNTIME_DIR:=/srv/fgbears-live/runtime}"
: "${PODCAST_AUDIO_FILTER:=highpass=f=70:poles=2,afftdn=nr=8:nf=-45:tn=1,equalizer=f=160:t=q:w=1:g=1.5,equalizer=f=320:t=q:w=1.1:g=-2,equalizer=f=3000:t=q:w=0.9:g=2,deesser=i=0.25:m=0.5:f=0.5,acompressor=threshold=0.125:ratio=3:attack=15:release=180:makeup=1.4:knee=3,loudnorm=I=-16:TP=-1.5:LRA=7,aresample=48000:async=1:first_pts=0}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ -s "$PLAYLIST_FILE" ]] || { echo "Playlist is missing or empty: $PLAYLIST_FILE" >&2; exit 66; }
[[ -r "$AD_OVERLAY_SCRIPT" ]] || { echo "Ad overlay renderer is missing: $AD_OVERLAY_SCRIPT" >&2; exit 66; }
[[ -r "$CRAWL_OVERLAY_SCRIPT" ]] || { echo "Crawl overlay renderer is missing: $CRAWL_OVERLAY_SCRIPT" >&2; exit 66; }

python3 "$AD_OVERLAY_SCRIPT" &
OVERLAY_PID=$!
python3 "$CRAWL_OVERLAY_SCRIPT" &
CRAWL_PID=$!

cleanup() {
  if [[ -n "${FFMPEG_PID:-}" ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
    kill -INT "$FFMPEG_PID" 2>/dev/null || true
    wait "$FFMPEG_PID" 2>/dev/null || true
  fi
  if [[ -n "${AD_MONITOR_PID:-}" ]] && kill -0 "$AD_MONITOR_PID" 2>/dev/null; then
    kill "$AD_MONITOR_PID" 2>/dev/null || true
    wait "$AD_MONITOR_PID" 2>/dev/null || true
  fi
  if kill -0 "$OVERLAY_PID" 2>/dev/null; then
    kill "$OVERLAY_PID" 2>/dev/null || true
    wait "$OVERLAY_PID" 2>/dev/null || true
  fi
  if kill -0 "$CRAWL_PID" 2>/dev/null; then
    kill "$CRAWL_PID" 2>/dev/null || true
    wait "$CRAWL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null; then
    break
  fi
  if ! kill -0 "$OVERLAY_PID" 2>/dev/null; then
    echo "Ad overlay renderer exited before becoming healthy." >&2
    exit 70
  fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${AD_OVERLAY_PORT}/healthz" >/dev/null || {
  echo "Ad overlay renderer did not become healthy." >&2
  exit 70
}
for _ in {1..30}; do
  if curl --silent --fail --max-time 1 "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/healthz" >/dev/null; then
    break
  fi
  if ! kill -0 "$CRAWL_PID" 2>/dev/null; then
    echo "Crawl overlay renderer exited before becoming healthy." >&2
    exit 70
  fi
  sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/healthz" >/dev/null || {
  echo "Crawl overlay renderer did not become healthy." >&2
  exit 70
}
for runtime_file in "$AD_FRAME_FILE" "$CRAWL_RUNTIME_DIR/crawl-label.txt" "$CRAWL_RUNTIME_DIR/crawl-message.txt"; do
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
AD_MONITOR_PID=""
monitor_ad_frame() {
  local initial current
  initial=$(cat "${AD_FRAME_FILE%.jpg}.sha256" 2>/dev/null || true)
  while sleep 10; do
    current=$(cat "${AD_FRAME_FILE%.jpg}.sha256" 2>/dev/null || true)
    if [[ -n "$initial" && -n "$current" && "$current" != "$initial" ]]; then
      echo "Advertising creative changed; refreshing the locally clocked stream." >&2
      kill -INT "$FFMPEG_PID" 2>/dev/null || true
      return
    fi
  done
}

# The source's normalized 30 fps timeline is the authoritative clock. The
# permanent advertising screen fully covers it, so source video never appears,
# while a slow overlay can no longer slow the whole broadcast.
ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -progress pipe:1 -stats_period 5 \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -i "$AD_FRAME_FILE" \
  -filter_complex "[1:v]scale=1280:720[ad];[0:v][ad]overlay=x=0:y=0:eof_action=repeat:shortest=0,drawbox=x=0:y=578:w=1280:h=118:color=0x07101F@0.95:t=fill,drawbox=x=0:y=578:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=585:w=245:h=111:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/crawl-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=29:x=(245-text_w)/2:y=620,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/crawl-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=31:x=w-mod(t*105\,w+text_w+100):y=620,format=yuv420p[v]" \
  -map "[v]" -map 0:a:0 \
  -c:v libx264 -preset superfast -tune zerolatency -profile:v high \
  -b:v 4000k -maxrate 4500k -bufsize 8000k \
  -g 60 -keyint_min 60 -sc_threshold 0 -r 30 -fps_mode cfr -threads 2 \
  -af "$PODCAST_AUDIO_FILTER" \
  -c:a aac -b:a 160k -ar 48000 -ac 2 \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}" > >(progress_sink) &
FFMPEG_PID=$!
monitor_ad_frame &
AD_MONITOR_PID=$!
set +e
wait "$FFMPEG_PID"
status=$?
set -e
kill "$AD_MONITOR_PID" 2>/dev/null || true
wait "$AD_MONITOR_PID" 2>/dev/null || true
exit "$status"


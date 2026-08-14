#!/usr/bin/env bash
# The cleanup handler is invoked indirectly by traps.
# shellcheck disable=SC2317
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
: "${BEARS_NEWS_SCRIPT:=/opt/fgbears-live/bin/bears-news-feed.py}"
: "${BEARS_NEWS_SCROLL_PPS:=90}"
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
[[ -r "$BEARS_NEWS_SCRIPT" ]] || { echo "Bears news feed poller is missing: $BEARS_NEWS_SCRIPT" >&2; exit 66; }

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
  if kill -0 "$OVERLAY_PID" 2>/dev/null; then
    kill "$OVERLAY_PID" 2>/dev/null || true
    wait "$OVERLAY_PID" 2>/dev/null || true
  fi
  if kill -0 "$CRAWL_PID" 2>/dev/null; then
    kill "$CRAWL_PID" 2>/dev/null || true
    wait "$CRAWL_PID" 2>/dev/null || true
  fi
  if kill -0 "$NEWS_PID" 2>/dev/null; then
    kill "$NEWS_PID" 2>/dev/null || true
    wait "$NEWS_PID" 2>/dev/null || true
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

for _ in {1..50}; do
  if [[ -e "$CRAWL_RUNTIME_DIR/bears-news-label.txt" && -e "$CRAWL_RUNTIME_DIR/bears-news-message.txt" ]]; then
    break
  fi
  if ! kill -0 "$NEWS_PID" 2>/dev/null; then
    echo "Bears news feed poller exited before publishing runtime text." >&2
    exit 70
  fi
  sleep 0.2
done

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

# Keep one 30 fps source clock. News and crawl are rendered inside true cropped
# sub-canvases, then overlaid back into their assigned message windows. Their
# pixels cannot exist outside those windows. Each lane is bounded by orange at
# x=262..266 on the left and x=1257..1261 on the right; the visible text area
# is exactly x=267..1256. Bears-blue gutters/dividers remain outside the lanes.
ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -progress pipe:3 -stats_period 5 \
  -re -stream_loop -1 -fflags +genpts \
  -f concat -safe 0 -i "$PLAYLIST_FILE" \
  -loop 1 -framerate 30 -i "$AD_FRAME_FILE" \
  -filter_complex "[1:v]scale=1280:720,split=3[base0][news0][crawl0];[news0]crop=w=990:h=68:x=267:y=23,drawbox=x=0:y=0:w=990:h=68:color=0x07101F@0.98:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/bears-news-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=25:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\,text_w+990):y=(h-text_h)/2[newslane];[crawl0]crop=w=990:h=108:x=267:y=589,drawbox=x=0:y=0:w=990:h=108:color=0x07101F@0.95:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/crawl-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=31:x=990-mod(t*105\,text_w+990):y=(h-text_h)/2[crawllane];[base0]drawbox=x=7:y=7:w=1266:h=97:color=0x0B162A:t=fill,drawbox=x=18:y=18:w=1244:h=78:color=0x07101F@0.98:t=fill,drawbox=x=18:y=18:w=244:h=78:color=0xC83803:t=fill,drawbox=x=18:y=18:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=91:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=18:w=5:h=78:color=0xC83803:t=fill,drawbox=x=1257:y=18:w=5:h=78:color=0xC83803:t=fill,drawbox=x=257:y=23:w=5:h=68:color=0x0B162A:t=fill,drawbox=x=262:y=23:w=5:h=68:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/bears-news-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=24:x=18+(239-text_w)/2:y=44,drawbox=x=7:y=100:w=1266:h=4:color=0x0B162A:t=fill,drawbox=x=7:y=574:w=1266:h=139:color=0x0B162A:t=fill,drawbox=x=18:y=584:w=1244:h=118:color=0x07101F@0.95:t=fill,drawbox=x=18:y=584:w=244:h=118:color=0xC83803:t=fill,drawbox=x=18:y=584:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=697:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=584:w=5:h=118:color=0xC83803:t=fill,drawbox=x=1257:y=584:w=5:h=118:color=0xC83803:t=fill,drawbox=x=257:y=589:w=5:h=108:color=0x0B162A:t=fill,drawbox=x=262:y=589:w=5:h=108:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/crawl-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=29:x=18+(239-text_w)/2:y=626,drawbox=x=7:y=574:w=1266:h=4:color=0x0B162A:t=fill[base];[base][newslane]overlay=x=267:y=23:shortest=1[withnews];[withnews][crawllane]overlay=x=267:y=589:shortest=1,drawbox=x=0:y=0:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=713:w=1280:h=7:color=0xC83803:t=fill,drawbox=x=0:y=0:w=7:h=720:color=0xC83803:t=fill,drawbox=x=1273:y=0:w=7:h=720:color=0xC83803:t=fill,format=yuv420p[v]" \
  -map "[v]" -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -b:v 4000k -maxrate 4500k -bufsize 8000k \
  -g 60 -keyint_min 60 -sc_threshold 0 -r 30 -fps_mode cfr -threads 2 \
  -af "$PODCAST_AUDIO_FILTER" \
  -c:a aac -b:a 160k -ar 48000 -ac 2 \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}" 3> >(progress_sink) &
FFMPEG_PID=$!
set +e
wait "$FFMPEG_PID"
status=$?
set -e
exit "$status"

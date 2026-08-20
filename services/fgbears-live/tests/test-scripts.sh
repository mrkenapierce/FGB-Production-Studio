#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
OVERLAY_PID=""
CRAWL_PID=""
cleanup() {
  for pid in "$OVERLAY_PID" "$CRAWL_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

for script in "$ROOT"/bin/*.sh; do
  bash -n "$script"
done
python3 -m py_compile "$ROOT/bin/ad-overlay.py" "$ROOT/bin/crawl-overlay.py" "$ROOT/bin/bears-news-feed.py"

grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${AD_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-preset ultrafast' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-progress pipe:3' "$ROOT/bin/start-stream.sh"
grep -Fq 'loudnorm=I=-16:TP=-1.5:LRA=7' "$ROOT/bin/start-stream.sh"
grep -Fq 'acompressor=threshold=0.125:ratio=3' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-c:a aac -b:a 128k -ar 48000 -ac 2' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
grep -Fq 'onfail=abort' "$ROOT/bin/start-stream.sh"
grep -Fq 'onfail=ignore' "$ROOT/bin/start-stream.sh"
grep -Fq 'StartLimitBurst=3' "$ROOT/systemd/fgbears-live.service"
grep -Fq 'Restart=on-failure' "$ROOT/systemd/fgbears-live.service"

if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then
  echo 'A real stream.env file must never be committed.' >&2
  exit 1
fi

cat > "$TMP/feed.json" <<'JSON'
{"kind":"house","sponsors":[{"businessName":"FGB","imageUrl":null,"promoMessage":"Bear Down","website":"https://epiccontentcreatorgrants.org/epic-media"}]}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" AD_FRAME_FILE="$TMP/runtime/ad-frame.jpg" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay.py" >"$TMP/ad-overlay.log" 2>&1 &
OVERLAY_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18787/healthz >"$TMP/ad-health.json" && break
  sleep 0.1
done
jq -e '.ok == true' "$TMP/ad-health.json" >/dev/null
curl --silent --fail http://127.0.0.1:18787/frame.jpg -o "$TMP/ad-frame.jpg"
python3 - "$TMP/ad-frame.jpg" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]); im.load(); assert im.size == (1280, 720), im.size
PY
kill "$OVERLAY_PID"; wait "$OVERLAY_PID" 2>/dev/null || true; OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"FGB LIVE","message":"🐻⬇️ #FGB 💙🧡","speed":"normal","updatedAt":"2026-08-19T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_RUNTIME_DIR="$TMP/runtime" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl-overlay.log" 2>&1 &
CRAWL_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18788/healthz >"$TMP/crawl-health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .active == true' "$TMP/crawl-health.json" >/dev/null
curl --silent --fail http://127.0.0.1:18788/frame.jpg -o "$TMP/crawl-frame.jpg"
python3 - "$TMP/crawl-frame.jpg" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]); im.load(); assert im.size == (1280, 139), im.size
PY
kill "$CRAWL_PID"; wait "$CRAWL_PID" 2>/dev/null || true; CRAWL_PID=""

mkdir -p "$TMP/media"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=640x360:r=24:d=0.5 \
  -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.5 \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$TMP/source.mp4"
MEDIA_DIR="$TMP/media" bash "$ROOT/bin/normalize-library.sh" "$TMP/source.mp4" "$TMP/media/episode-01.mp4"
bash "$ROOT/bin/validate-media.sh" "$TMP/media"
MEDIA_DIR="$TMP/media" PLAYLIST_FILE="$TMP/playlist.ffconcat" bash "$ROOT/bin/rebuild-playlist.sh"
grep -q 'episode-01.mp4' "$TMP/playlist.ffconcat"

echo 'FGBears Live integration tests passed.'

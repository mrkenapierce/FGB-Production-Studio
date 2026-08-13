#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
OVERLAY_PID=""
CRAWL_PID=""
cleanup() {
  if [[ -n "$OVERLAY_PID" ]] && kill -0 "$OVERLAY_PID" 2>/dev/null; then
    kill "$OVERLAY_PID" 2>/dev/null || true
    wait "$OVERLAY_PID" 2>/dev/null || true
  fi
  if [[ -n "$CRAWL_PID" ]] && kill -0 "$CRAWL_PID" 2>/dev/null; then
    kill "$CRAWL_PID" 2>/dev/null || true
    wait "$CRAWL_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

for script in "$ROOT"/bin/*.sh; do
  bash -n "$script"
done
python3 -m py_compile "$ROOT/bin/ad-overlay.py"
python3 -m py_compile "$ROOT/bin/crawl-overlay.py"

grep -q 'REPLACE_WITH_YOUTUBE_STREAM_KEY' "$ROOT/config/stream.env.example"
if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then
  echo 'A real stream.env file must never be committed.' >&2
  exit 1
fi

cat > "$TMP/feed.json" <<'JSON'
{"kind":"house","sponsors":[{"businessName":"Preseason Game One is 8/15/2026","imageUrl":null,"promoMessage":"Join us for trivia and giveaways!","website":"https://epiccontentcreatorgrants.org/epic-media"}]}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay.py" >"$TMP/ad-overlay.log" 2>&1 &
OVERLAY_PID=$!
for _ in {1..30}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18787/healthz >"$TMP/health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .kind == "house" and .sponsorCount == 1' "$TMP/health.json" >/dev/null
curl --silent --fail http://127.0.0.1:18787/frame.jpg -o "$TMP/frame.jpg"
python3 - "$TMP/frame.jpg" <<'PY'
import sys
from PIL import Image
img = Image.open(sys.argv[1])
assert img.size == (1280, 720), img.size
PY
kill "$OVERLAY_PID"
wait "$OVERLAY_PID" 2>/dev/null || true
OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"EPIC LIVE","message":"TRIVIA & GIVEAWAYS ARE LIVE — VISIT EPICCONTENTCREATORGRANTS.ORG/EPIC-MEDIA TO PARTICIPATE","speed":"normal","updatedAt":"2026-08-12T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl-overlay.log" 2>&1 &
CRAWL_PID=$!
for _ in {1..30}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18788/healthz >"$TMP/crawl-health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .active == true' "$TMP/crawl-health.json" >/dev/null
curl --silent --fail http://127.0.0.1:18788/frame.png -o "$TMP/crawl.png"
python3 - "$TMP/crawl.png" <<'PY'
import sys
from PIL import Image
img = Image.open(sys.argv[1])
assert img.size == (1280, 118), img.size
assert img.mode == "RGBA", img.mode
PY
kill "$CRAWL_PID"
wait "$CRAWL_PID" 2>/dev/null || true
CRAWL_PID=""

mkdir -p "$TMP/media"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=640x360:r=24:d=0.5 \
  -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.5 \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$TMP/source.mp4"
MEDIA_DIR="$TMP/media" bash "$ROOT/bin/normalize-library.sh" "$TMP/source.mp4" "$TMP/media/episode-01.mp4"
bash "$ROOT/bin/validate-media.sh" "$TMP/media"
MEDIA_DIR="$TMP/media" PLAYLIST_FILE="$TMP/playlist.ffconcat" bash "$ROOT/bin/rebuild-playlist.sh"
grep -q "episode-01.mp4" "$TMP/playlist.ffconcat"

echo 'FGBears Live script tests passed.'

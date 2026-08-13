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
grep -Fq 'def fit_text_block(' "$ROOT/bin/ad-overlay.py"
grep -Fq 'supplied_subtitle' "$ROOT/bin/ad-overlay.py"
test "$(grep -Fc 'message.upper(), text_x, y, text_w' "$ROOT/bin/ad-overlay.py")" -eq 2
test "$(grep -F 'message.upper(), text_x, y, text_w' "$ROOT/bin/ad-overlay.py" | grep -Fc '"#0B162A"')" -eq 2
python3 -m py_compile "$ROOT/bin/crawl-overlay.py"
grep -q '^AD_OVERLAY_FPS=25$' "$ROOT/config/stream.env.example"

grep -q 'REPLACE_WITH_YOUTUBE_STREAM_KEY' "$ROOT/config/stream.env.example"
# The dollar expression is intentionally literal: this verifies the script text.
# shellcheck disable=SC2016
grep -Fq -- '-i "$AD_FRAME_FILE"' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-loop 1 -framerate 30' "$ROOT/bin/start-stream.sh"
if grep -Fq -- '-re -loop 1' "$ROOT/bin/start-stream.sh"; then
  echo 'The still image must not have a second independent rate limiter.' >&2
  exit 1
fi
grep -Fq -- '-preset ultrafast' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-progress pipe:3' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawtext=fontfile=' "$ROOT/bin/start-stream.sh"
python3 - "$ROOT/bin/start-stream.sh" <<'PY'
import sys
text = open(sys.argv[1], encoding="utf-8").read()
message = text.index("crawl-message.txt")
mask = text.index("drawbox=x=0:y=585:w=275", message)
label = text.index("crawl-label.txt", mask)
assert message < mask < label, "crawl text must be masked before the fixed label is drawn"
PY
grep -Fq 'FFMPEG_PROGRESS_FILE' "$ROOT/bin/start-stream.sh"
grep -Fq 'FFMPEG_HEALTH_SAMPLE_FILE' "$ROOT/bin/healthcheck.sh"
grep -Fq 'instant_speed=' "$ROOT/bin/healthcheck.sh"
grep -Fq 'loudnorm=I=-16:TP=-1.5:LRA=7' "$ROOT/bin/start-stream.sh"
grep -Fq 'acompressor=threshold=0.125:ratio=3' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-c:a aac -b:a 160k -ar 48000 -ac 2' "$ROOT/bin/start-stream.sh"
if grep -Fq -- '-c:a copy' "$ROOT/bin/start-stream.sh"; then
  echo 'Podcast processing requires audio encoding, not AAC passthrough.' >&2
  exit 1
fi
if grep -Eq "enable=.*mod\\(t" "$ROOT/bin/start-stream.sh"; then
  echo 'The permanent advertising screen must not use timed visibility.' >&2
  exit 1
fi
if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then
  echo 'A real stream.env file must never be committed.' >&2
  exit 1
fi

cat > "$TMP/feed.json" <<'JSON'
{"kind":"house","sponsors":[{"businessName":"Preseason Game One is 8/15/2026","imageUrl":null,"promoMessage":"Join us for trivia and giveaways!","website":"https://epiccontentcreatorgrants.org/epic-media"}]}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" AD_FRAME_FILE="$TMP/runtime/ad-frame.jpg" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay.py" >"$TMP/ad-overlay.log" 2>&1 &
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
test -s "$TMP/runtime/ad-frame.jpg"
test -s "$TMP/runtime/ad-frame.sha256"
kill "$OVERLAY_PID"
wait "$OVERLAY_PID" 2>/dev/null || true
OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"EPIC LIVE","message":"TRIVIA & GIVEAWAYS ARE LIVE — VISIT EPICCONTENTCREATORGRANTS.ORG/EPIC-MEDIA TO PARTICIPATE","speed":"normal","updatedAt":"2026-08-12T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_RUNTIME_DIR="$TMP/runtime" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl-overlay.log" 2>&1 &
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
grep -q '^EPIC LIVE$' "$TMP/runtime/crawl-label.txt"
grep -q 'TRIVIA & GIVEAWAYS' "$TMP/runtime/crawl-message.txt"
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

# Prove the permanent ad and reloadable crawl render over the source-owned clock.
mkdir -p "$TMP/runtime"
cp "$TMP/frame.jpg" "$TMP/runtime/ad-frame.jpg"
printf 'EPIC LIVE\n' > "$TMP/runtime/crawl-label.txt"
printf 'TEST CRAWL MESSAGE\n' > "$TMP/runtime/crawl-message.txt"
ffmpeg -hide_banner -loglevel error \
  -re -loop 1 -framerate 30 -i "$TMP/runtime/ad-frame.jpg" \
  -filter_complex "[0:v]scale=1280:720,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/crawl-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=31:x=w-mod(t*105\\,w+text_w+100):y=620,format=yuv420p[v]" \
  -map '[v]' -t 0.4 -c:v libx264 -preset ultrafast -an -f null -

echo 'FGBears Live script tests passed.'

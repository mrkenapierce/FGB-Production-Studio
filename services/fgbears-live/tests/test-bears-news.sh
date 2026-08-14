#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
PID=""
cleanup() {
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

python3 -m py_compile "$ROOT/bin/bears-news-feed.py"
bash -n "$ROOT/bin/start-stream.sh"
grep -Fq 'BEARS_NEWS_OVERLAY_PORT' "$ROOT/bin/start-stream.sh"
grep -Fq 'video_size 1244x78' "$ROOT/bin/start-stream.sh"
grep -Fq 'overlay=x=18:y=18' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=0:y=578:w=1280:h=118' "$ROOT/bin/start-stream.sh"
grep -q '^BEARS_NEWS_OVERLAY_PORT=8789$' "$ROOT/config/stream.env.example"
grep -q '^BEARS_NEWS_SCROLL_PPS=90$' "$ROOT/config/stream.env.example"

cat > "$TMP/feed.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item>
  <title>This is a deliberately long Chicago Bears headline that must scroll completely through the upper third without clipping the final source characters</title>
  <source url="https://www.chicagobears.com/">ChicagoBears.com</source>
  <category>normal</category>
</item>
<item><title>Major Bears update</title><source url="https://example.com">Second Source</source><category>breaking</category></item>
</channel></rss>
XML

BEARS_NEWS_FEED_FILE="$TMP/feed.xml" \
CRAWL_RUNTIME_DIR="$TMP/runtime" \
BEARS_NEWS_OVERLAY_PORT=18789 \
BEARS_NEWS_OVERLAY_FPS=15 \
BEARS_NEWS_POLL_SECONDS=30 \
BEARS_NEWS_STATIC_SECONDS=8 \
BEARS_NEWS_SCROLL_PPS=300 \
python3 "$ROOT/bin/bears-news-feed.py" >"$TMP/news.log" 2>&1 &
PID=$!
for _ in {1..50}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18789/healthz >"$TMP/health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .active == true' "$TMP/health.json" >/dev/null

grep -q '^BEARS NEWS$' "$TMP/runtime/bears-news-label.txt"
grep -q 'CHICAGOBEARS.COM$' "$TMP/runtime/bears-news-message.txt"
grep -q 'FINAL SOURCE CHARACTERS' "$TMP/runtime/bears-news-message.txt"
grep -q '^1$' "$TMP/runtime/bears-news-active"

curl --silent --fail http://127.0.0.1:18789/frame.png -o "$TMP/news.png"
python3 - "$TMP/news.png" "$ROOT/bin/bears-news-feed.py" <<'PY'
import runpy
import sys
from PIL import Image

img = Image.open(sys.argv[1]).convert("RGBA")
assert img.size == (1244, 78), img.size
orange = (200, 56, 3, 255)
# Orange border must be present on all four sides.
for point in ((2, 2), (1241, 2), (2, 75), (1241, 75), (620, 2), (620, 75)):
    assert img.getpixel(point) == orange, (point, img.getpixel(point))

module = runpy.run_path(sys.argv[2])
message = "THIS IS A VERY LONG BEARS HEADLINE " * 8 + "SOURCE: CHICAGOBEARS.COM"
_, width, height = module["text_metrics"](message)
assert height < module["HEIGHT"], (height, module["HEIGHT"])
assert width > module["VIEWPORT_WIDTH"], (width, module["VIEWPORT_WIDTH"])
duration = module["display_duration"](message)
minimum = (module["VIEWPORT_WIDTH"] + width + 80) / module["SCROLL_PPS"] + 1.5
assert duration >= minimum, (duration, minimum)
PY

# Prove FFmpeg can consume the renderer's raw RGBA stream and composite it into
# the exact upper-third position used by production.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=1280x720:r=30:d=0.3 \
  -f rawvideo -pixel_format rgba -video_size 1244x78 -framerate 15 -i http://127.0.0.1:18789/overlay.rgba \
  -filter_complex '[0:v][1:v]overlay=x=18:y=18:format=auto,format=yuv420p[v]' \
  -map '[v]' -t 0.3 -f null -

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news clipping and completeness tests passed.'

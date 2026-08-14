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
if grep -Fq 'LABEL_GAP' "$ROOT/bin/bears-news-feed.py"; then
  echo 'Bears news must not leave a blue gap before the orange label.' >&2
  exit 1
fi

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
module = runpy.run_path(sys.argv[2])
assert img.size == (module["WIDTH"], module["HEIGHT"]), img.size
orange = module["BEARS_ORANGE"]
border = module["OUTER_BORDER"]
width = module["WIDTH"]
height = module["HEIGHT"]

# Every pixel of every outer side must be the same exact Bears Orange thickness.
for y in range(border):
    for x in range(width):
        assert img.getpixel((x, y)) == orange, ("top", x, y, img.getpixel((x, y)))
for y in range(height - border, height):
    for x in range(width):
        assert img.getpixel((x, y)) == orange, ("bottom", x, y, img.getpixel((x, y)))
for x in range(border):
    for y in range(height):
        assert img.getpixel((x, y)) == orange, ("left", x, y, img.getpixel((x, y)))
for x in range(width - border, width):
    for y in range(height):
        assert img.getpixel((x, y)) == orange, ("right", x, y, img.getpixel((x, y)))

# The visible headline region begins immediately after the orange label. There
# may not be an intermediate blue spacer where moving text can vanish early.
assert module["VIEWPORT_START"] == module["LABEL_RIGHT"] + 1
safe_y = border + 2
assert img.getpixel((module["LABEL_RIGHT"], safe_y)) == orange

message = "THIS IS A VERY LONG BEARS HEADLINE " * 8 + "SOURCE: CHICAGOBEARS.COM"
_, text_width, text_height = module["text_metrics"](message)
assert text_height < height - 2 * border, (text_height, height, border)
assert text_width > module["VIEWPORT_WIDTH"], (text_width, module["VIEWPORT_WIDTH"])

# At the end of the calculated travel, the final character is fully underneath
# the orange label. Rotation is not allowed until an additional trailing hold.
travel = module["scroll_travel"](text_width)
end_elapsed = travel / module["SCROLL_PPS"]
end_x = module["headline_x"](text_width, end_elapsed)
assert end_x + text_width <= module["VIEWPORT_START"], (
    end_x,
    text_width,
    module["VIEWPORT_START"],
)
duration = module["display_duration"](message)
assert duration >= end_elapsed + module["SCROLL_END_HOLD"], (
    duration,
    end_elapsed,
    module["SCROLL_END_HOLD"],
)
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

echo 'Bears news frame, mask, and completeness tests passed.'

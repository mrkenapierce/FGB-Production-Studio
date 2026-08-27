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
python3 - "$ROOT/bin/bears-news-feed.py" <<'PY'
import importlib.util
import sys
import urllib.parse
spec = importlib.util.spec_from_file_location('bears_news_feed', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
url = module.cache_busted_feed_url()
query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
assert query.get('_refresh') and query['_refresh'][0].isdigit(), url
assert module.WIDTH == 1280 and module.HEIGHT == 104
assert module.VIEWPORT_WIDTH == 990 and module.VIEWPORT_HEIGHT == 68
assert module.SCROLL_PPS == 76
PY
bash -n "$ROOT/bin/start-stream.sh"

# News now uses the same stable MJPEG image-composition model as the lower
# crawl. Rawvideo remains forbidden because it previously created pacing lag.
if grep -Fq -- '-f rawvideo' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news must not use a rawvideo input.' >&2
  exit 1
fi
grep -Fq 'BEARS_NEWS_OVERLAY_PORT:=8789' "$ROOT/bin/start-stream.sh"
grep -Fq 'BEARS_NEWS_OVERLAY_FPS:=30' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
grep -Fq '[1:v][3:v]overlay=x=0:y=0:shortest=1[withnews]' "$ROOT/bin/start-stream.sh"
grep -Fq '[withnews][2:v]overlay=x=0:y=574:shortest=1' "$ROOT/bin/start-stream.sh"

# The retired FFmpeg glyph-rendering path must stay gone.
if grep -Fq 'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$CRAWL_RUNTIME_DIR/bears-news-message.txt' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news was routed back through FFmpeg drawtext.' >&2
  exit 1
fi
if grep -Fq '[news0]crop=' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news was routed back through the retired FFmpeg crop lane.' >&2
  exit 1
fi

# Full-overlay outer perimeter stays Chicago Bears Orange.
for spec in \
  'drawbox=x=0:y=0:w=1280:h=7:color=0xC83803' \
  'drawbox=x=0:y=713:w=1280:h=7:color=0xC83803' \
  'drawbox=x=0:y=0:w=7:h=720:color=0xC83803' \
  'drawbox=x=1273:y=0:w=7:h=720:color=0xC83803'; do
  grep -Fq "$spec" "$ROOT/bin/start-stream.sh"
done

cat > "$TMP/feed.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item>
  <title>This is a deliberately long Chicago Bears headline that must remain complete through the source</title>
  <source url="https://www.chicagobears.com/">ChicagoBears.com</source>
  <category>normal</category>
</item>
<item>
  <title>Major Bears update</title>
  <source url="https://example.com">Second Source</source>
  <category>breaking</category>
</item>
</channel></rss>
XML

BEARS_NEWS_FEED_FILE="$TMP/feed.xml" \
CRAWL_RUNTIME_DIR="$TMP/runtime" \
BEARS_NEWS_OVERLAY_PORT=18789 \
BEARS_NEWS_OVERLAY_FPS=30 \
BEARS_NEWS_POLL_SECONDS=30 \
python3 "$ROOT/bin/bears-news-feed.py" >"$TMP/news.log" 2>&1 &
PID=$!
for _ in {1..50}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:18789/healthz >"$TMP/health.json" 2>/dev/null; then
    break
  fi
  sleep 0.1
done

python3 - "$TMP/health.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding='utf-8'))
assert value['ok'] is True
assert value['active'] is True
assert value['renderer'] == 'pillow-mjpeg'
assert value['fps'] == 30
assert value['messageChars'] > 100
PY

grep -q '^BEARS NEWS$' "$TMP/runtime/bears-news-label.txt"
grep -Fq 'THIS IS A DELIBERATELY LONG CHICAGO BEARS HEADLINE THAT MUST REMAIN COMPLETE THROUGH THE SOURCE' "$TMP/runtime/bears-news-message.txt"
grep -q 'CHICAGOBEARS.COM' "$TMP/runtime/bears-news-message.txt"
grep -q 'BREAKING: MAJOR BEARS UPDATE' "$TMP/runtime/bears-news-message.txt"
grep -q 'SOURCE: SECOND SOURCE' "$TMP/runtime/bears-news-message.txt"
grep -q '◆' "$TMP/runtime/bears-news-message.txt"
grep -q '^1$' "$TMP/runtime/bears-news-active"

curl --silent --fail --max-time 3 http://127.0.0.1:18789/frame.png -o "$TMP/news.png"
curl --silent --fail --max-time 3 http://127.0.0.1:18789/frame.jpg -o "$TMP/news.jpg"
python3 - "$TMP/news.png" "$TMP/news.jpg" <<'PY'
from PIL import Image
import sys
for path in sys.argv[1:]:
    im = Image.open(path)
    im.load()
    assert im.size == (1280, 104), (path, im.size)
# Confirm the rendered panel is not blank/transparent.
png = Image.open(sys.argv[1]).convert('RGBA')
assert png.getbbox() is not None
PY

# Parse and execute the production composition graph using synthetic images.
python3 - "$ROOT/bin/start-stream.sh" <<'PY'
import re
import subprocess
import sys

script = open(sys.argv[1], encoding='utf-8').read()
match = re.search(r'-filter_complex "(.*?)" \\\n', script, re.S)
assert match, 'production filter graph not found'
graph = match.group(1)
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:r=30:d=0.4',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:r=30:d=0.4',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x139:r=30:d=0.4',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x104:r=30:d=0.4',
    '-filter_complex', graph, '-map', '[v]', '-t', '0.4', '-f', 'null', '-'
], check=True)
PY

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news image-renderer composition tests passed.'

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

# Preserve the single-clock A/V-safe design.
if grep -Fq -- '-f rawvideo' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news must not use a rawvideo input; it can cause A/V pacing lag.' >&2
  exit 1
fi
if grep -Fq 'BEARS_NEWS_OVERLAY_PORT' "$ROOT/bin/start-stream.sh"; then
  echo 'The retired Bears news HTTP overlay must not be referenced.' >&2
  exit 1
fi
grep -q '^BEARS_NEWS_SCROLL_PPS=90$' "$ROOT/config/stream.env.example"

# Full-overlay outer perimeter stays Chicago Bears Orange.
for spec in \
  'drawbox=x=0:y=0:w=1280:h=7:color=0xC83803' \
  'drawbox=x=0:y=713:w=1280:h=7:color=0xC83803' \
  'drawbox=x=0:y=0:w=7:h=720:color=0xC83803' \
  'drawbox=x=1273:y=0:w=7:h=720:color=0xC83803'; do
  grep -Fq "$spec" "$ROOT/bin/start-stream.sh"
done

# Explicit Bears-blue gutters separate both dynamic ribbons from the outer frame.
grep -Fq 'drawbox=x=7:y=7:w=1266:h=97:color=0x0B162A' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=7:y=574:w=1266:h=139:color=0x0B162A' "$ROOT/bin/start-stream.sh"

# News and crawl retain matching inset orange frames.
for spec in \
  'drawbox=x=18:y=18:w=1244:h=5:color=0xC83803' \
  'drawbox=x=18:y=91:w=1244:h=5:color=0xC83803' \
  'drawbox=x=18:y=18:w=5:h=78:color=0xC83803' \
  'drawbox=x=1257:y=18:w=5:h=78:color=0xC83803' \
  'drawbox=x=18:y=584:w=1244:h=5:color=0xC83803' \
  'drawbox=x=18:y=697:w=1244:h=5:color=0xC83803' \
  'drawbox=x=18:y=584:w=5:h=118:color=0xC83803' \
  'drawbox=x=1257:y=584:w=5:h=118:color=0xC83803'; do
  grep -Fq "$spec" "$ROOT/bin/start-stream.sh"
done

# Each moving ribbon has its own entry/exit lane. The dark masks are inside the
# message panel and are symmetric at x=262..282 and x=1237..1257.
for spec in \
  'drawbox=x=262:y=23:w=20:h=68:color=0x07101F' \
  'drawbox=x=1237:y=23:w=20:h=68:color=0x07101F' \
  'drawbox=x=262:y=589:w=20:h=108:color=0x07101F' \
  'drawbox=x=1237:y=589:w=20:h=108:color=0x07101F'; do
  grep -Fq "$spec" "$ROOT/bin/start-stream.sh"
done

# Internal divider lines remain Bears blue.
grep -Fq 'drawbox=x=257:y=23:w=5:h=68:color=0x0B162A' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=257:y=589:w=5:h=108:color=0x0B162A' "$ROOT/bin/start-stream.sh"

# Exact movement math: both long ribbons begin at the right lane edge (1237)
# and traverse exactly 955 pixels plus their own text width to clear at x=282.
# shellcheck disable=SC2016
grep -Fq '1237-mod(t*$BEARS_NEWS_SCROLL_PPS\,text_w+955)' "$ROOT/bin/start-stream.sh"
grep -Fq 'x=1237-mod(t*105\,text_w+955)' "$ROOT/bin/start-stream.sh"

# Ordering matters: moving text first, then edge masks, then fixed label/frame.
python3 - "$ROOT/bin/start-stream.sh" <<'PY'
import sys
text = open(sys.argv[1], encoding='utf-8').read()

news = text.index('bears-news-message.txt')
news_left = text.index('drawbox=x=262:y=23:w=20:h=68', news)
news_right = text.index('drawbox=x=1237:y=23:w=20:h=68', news_left)
news_label_box = text.index('drawbox=x=18:y=18:w=244:h=78', news_right)
news_label = text.index('bears-news-label.txt', news_label_box)
assert news < news_left < news_right < news_label_box < news_label

crawl = text.index('crawl-message.txt')
crawl_left = text.index('drawbox=x=262:y=589:w=20:h=108', crawl)
crawl_right = text.index('drawbox=x=1237:y=589:w=20:h=108', crawl_left)
crawl_label_box = text.index('drawbox=x=18:y=584:w=244:h=118', crawl_right)
crawl_label = text.index('crawl-label.txt', crawl_label_box)
outer = text.index('drawbox=x=0:y=0:w=1280:h=7', crawl_label)
assert crawl < crawl_left < crawl_right < crawl_label_box < crawl_label < outer
PY

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
BEARS_NEWS_POLL_SECONDS=30 \
python3 "$ROOT/bin/bears-news-feed.py" >"$TMP/news.log" 2>&1 &
PID=$!
for _ in {1..50}; do
  [[ -s "$TMP/runtime/bears-news-message.txt" ]] && break
  sleep 0.1
done

grep -q '^BEARS NEWS$' "$TMP/runtime/bears-news-label.txt"
grep -q 'CHICAGOBEARS.COM' "$TMP/runtime/bears-news-message.txt"
grep -q 'BREAKING: MAJOR BEARS UPDATE' "$TMP/runtime/bears-news-message.txt"
grep -q 'SOURCE: SECOND SOURCE' "$TMP/runtime/bears-news-message.txt"
grep -q '◆' "$TMP/runtime/bears-news-message.txt"
grep -q '^1$' "$TMP/runtime/bears-news-active"

printf 'EPIC LIVE\n' > "$TMP/runtime/crawl-label.txt"
printf 'TEST CRAWL\n' > "$TMP/runtime/crawl-message.txt"

# Parse the production filter graph itself so the test cannot drift from the
# real FFmpeg composition.
python3 - "$ROOT/bin/start-stream.sh" "$TMP/runtime" <<'PY'
import re
import subprocess
import sys

script = open(sys.argv[1], encoding='utf-8').read()
runtime = sys.argv[2]
match = re.search(r'-filter_complex "(.*?)" \\\n', script, re.S)
assert match, 'production filter graph not found'
graph = match.group(1)
graph = graph.replace('[1:v]', '[0:v]', 1)
graph = graph.replace('$CRAWL_RUNTIME_DIR', runtime)
graph = graph.replace('$BEARS_NEWS_SCROLL_PPS', '90')
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:r=30:d=0.3',
    '-filter_complex', graph, '-map', '[v]', '-t', '0.3', '-f', 'null', '-'
], check=True)
PY

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Blue gutters, dedicated news/crawl lanes, full orange frame, and A/V-safe tests passed.'

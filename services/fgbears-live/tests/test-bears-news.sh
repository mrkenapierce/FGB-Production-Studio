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

# Bears-blue gutters separate both dynamic ribbons from the outer orange frame.
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

# Blue divider, then an orange left lane boundary. The row's orange right border
# is the other lane boundary. This makes the visible message lane x=267..1256.
grep -Fq 'drawbox=x=257:y=23:w=5:h=68:color=0x0B162A' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=262:y=23:w=5:h=68:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=257:y=589:w=5:h=108:color=0x0B162A' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=262:y=589:w=5:h=108:color=0xC83803' "$ROOT/bin/start-stream.sh"

# True clipping: moving words are rendered on cropped 990px sub-canvases, not
# on the full frame with painted masks. They are composited only into x=267..1256.
grep -Fq 'split=3[base0][news0][crawl0]' "$ROOT/bin/start-stream.sh"
grep -Fq '[news0]crop=w=990:h=68:x=267:y=23' "$ROOT/bin/start-stream.sh"
grep -Fq '[crawl0]crop=w=990:h=108:x=267:y=589' "$ROOT/bin/start-stream.sh"
grep -Fq '[base][newslane]overlay=x=267:y=23:shortest=1' "$ROOT/bin/start-stream.sh"
grep -Fq '[withnews][crawllane]overlay=x=267:y=589:shortest=1' "$ROOT/bin/start-stream.sh"

if grep -Fq 'drawbox=x=262:y=23:w=20' "$ROOT/bin/start-stream.sh" || \
   grep -Fq 'drawbox=x=1237:y=23:w=20' "$ROOT/bin/start-stream.sh" || \
   grep -Fq 'drawbox=x=262:y=589:w=20' "$ROOT/bin/start-stream.sh" || \
   grep -Fq 'drawbox=x=1237:y=589:w=20' "$ROOT/bin/start-stream.sh"; then
  echo 'Painted edge masks must not be used; the lanes must be physically clipped.' >&2
  exit 1
fi

# Each ribbon starts completely beyond the right interior orange line at local
# x=990, traverses exactly its own 990px lane plus text width, and therefore
# fully disappears at the left interior orange line before the cycle repeats.
# shellcheck disable=SC2016
grep -Fq 'x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\,text_w+990)' "$ROOT/bin/start-stream.sh"
grep -Fq 'x=990-mod(t*105\,text_w+990)' "$ROOT/bin/start-stream.sh"

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
printf 'TEST CRAWL MESSAGE THAT MUST ENTER AND EXIT ONLY INSIDE ITS OWN ORANGE LINES\n' > "$TMP/runtime/crawl-message.txt"

# Parse the exact production filter graph. This validates split/crop/drawtext/
# overlay geometry together on a single source clock.
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

echo 'True orange-line news/crawl clipping, blue gutters, and A/V-safe tests passed.'

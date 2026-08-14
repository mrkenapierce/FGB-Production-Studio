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

# The news layer must not add another live video clock/input to FFmpeg.
if grep -Fq -- '-f rawvideo' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news must not use a rawvideo input; it can cause A/V pacing lag.' >&2
  exit 1
fi
if grep -Fq 'BEARS_NEWS_OVERLAY_PORT' "$ROOT/bin/start-stream.sh"; then
  echo 'The retired Bears news HTTP overlay must not be referenced.' >&2
  exit 1
fi

grep -q '^BEARS_NEWS_SCROLL_PPS=90$' "$ROOT/config/stream.env.example"
if grep -q '^BEARS_NEWS_OVERLAY_' "$ROOT/config/stream.env.example"; then
  echo 'Retired Bears news overlay settings must not remain in the example config.' >&2
  exit 1
fi

# Exact Chicago Bears Orange perimeter and boundary geometry.
grep -Fq 'drawbox=x=18:y=18:w=1244:h=5:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=18:y=91:w=1244:h=5:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=18:y=18:w=5:h=78:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=1257:y=18:w=5:h=78:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=257:y=22:w=5:h=70:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=18:y=96:w=1244:h=4:color=0xC83803' "$ROOT/bin/start-stream.sh"
grep -Fq '1257-mod(t*$BEARS_NEWS_SCROLL_PPS\,text_w+1000)' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=0:y=578:w=1280:h=118' "$ROOT/bin/start-stream.sh"

# The moving text must be drawn before the orange masks/label so it disappears
# underneath orange rather than at a blue clipping edge.
python3 - "$ROOT/bin/start-stream.sh" <<'PY'
import sys
text = open(sys.argv[1], encoding='utf-8').read()
message = text.index('bears-news-message.txt')
left_mask = text.index('drawbox=x=0:y=18:w=262:h=78', message)
separator = text.index('drawbox=x=257:y=22:w=5:h=70', left_mask)
label = text.index('bears-news-label.txt', separator)
assert message < left_mask < separator < label
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

# Parse the production-style single-clock filter graph with real text files.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=1280x720:r=30:d=0.3 \
  -filter_complex "[0:v]drawbox=x=22:y=22:w=1235:h=70:color=0x0B162A@0.98:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/bears-news-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=25:x=1257-mod(t*90\,text_w+1000):y=44,drawbox=x=0:y=18:w=262:h=78:color=0xC83803:t=fill,drawbox=x=1257:y=18:w=23:h=78:color=0xC83803:t=fill,drawbox=x=18:y=18:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=91:w=1244:h=5:color=0xC83803:t=fill,drawbox=x=18:y=18:w=5:h=78:color=0xC83803:t=fill,drawbox=x=1257:y=18:w=5:h=78:color=0xC83803:t=fill,drawbox=x=257:y=22:w=5:h=70:color=0xC83803:t=fill,drawbox=x=18:y=96:w=1244:h=4:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/bears-news-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=24:x=(257-text_w)/2:y=44,format=yuv420p[v]" \
  -map '[v]' -t 0.3 -f null -

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news single-clock, completeness, and orange-boundary tests passed.'

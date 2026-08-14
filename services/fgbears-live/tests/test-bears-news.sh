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
grep -Fq 'bears-news-message.txt' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=18:y=18:w=1244:h=78' "$ROOT/bin/start-stream.sh"
grep -Fq 'x=if(lte(text_w\,974)\,268\,1262-mod(t*105\,text_w+994))' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=0:y=578:w=1280:h=118' "$ROOT/bin/start-stream.sh"
grep -Fq 'former upper-third title' "$ROOT/bin/start-stream.sh"
grep -q '^BEARS_NEWS_FEED_URL=' "$ROOT/config/stream.env.example"
grep -q '^BEARS_NEWS_ROTATE_SECONDS=30$' "$ROOT/config/stream.env.example"

cat > "$TMP/feed.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>Bagent to start Saturday as Bears rest several starters</title><source url="https://example.com">Test Source</source><category>normal</category></item>
<item><title>Major Bears update</title><source url="https://example.com">Second Source</source><category>breaking</category></item>
</channel></rss>
XML

BEARS_NEWS_FEED_FILE="$TMP/feed.xml" \
CRAWL_RUNTIME_DIR="$TMP/runtime" \
BEARS_NEWS_POLL_SECONDS=30 \
BEARS_NEWS_ROTATE_SECONDS=8 \
python3 "$ROOT/bin/bears-news-feed.py" >"$TMP/news.log" 2>&1 &
PID=$!
for _ in {1..30}; do
  [[ -s "$TMP/runtime/bears-news-message.txt" ]] && break
  sleep 0.1
done
grep -q '^BEARS NEWS$' "$TMP/runtime/bears-news-label.txt"
grep -q 'BAGENT TO START SATURDAY' "$TMP/runtime/bears-news-message.txt"
grep -q 'SOURCE: TEST SOURCE' "$TMP/runtime/bears-news-message.txt"
grep -q '^1$' "$TMP/runtime/bears-news-active"

# Verify the production filter graph parses for both the static-fit and scrolling
# paths without disturbing the existing lower crawl.
printf 'BEARS NEWS\n' > "$TMP/runtime/bears-news-label.txt"
printf 'THIS IS A LONG CHICAGO BEARS HEADLINE THAT SHOULD SCROLL THROUGH THE UPPER THIRD WHEN IT DOES NOT FIT ON SCREEN SOURCE REUTERS\n' > "$TMP/runtime/bears-news-message.txt"
printf 'EPIC LIVE\n' > "$TMP/runtime/crawl-label.txt"
printf 'TEST CRAWL\n' > "$TMP/runtime/crawl-message.txt"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=1280x720:r=30:d=0.2 \
  -filter_complex "[0:v]drawbox=x=18:y=18:w=1244:h=78:color=0x0B162A@0.98:t=fill,drawbox=x=18:y=18:w=1244:h=5:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/bears-news-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=24:x=if(lte(text_w\,974)\,268\,1262-mod(t*105\,text_w+994)):y=44,drawbox=x=18:y=23:w=250:h=73:color=0x0B162A@0.98:t=fill,drawbox=x=18:y=23:w=230:h=73:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/bears-news-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=24:x=18+(230-text_w)/2:y=44,drawbox=x=0:y=578:w=1280:h=118:color=0x07101F@0.95:t=fill,drawbox=x=0:y=578:w=1280:h=7:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/crawl-message.txt:reload=1:expansion=none:fontcolor=white:fontsize=31:x=w-mod(t*105\,w+text_w+100):y=620,drawbox=x=0:y=585:w=275:h=111:color=0xC83803:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:textfile=$TMP/runtime/crawl-label.txt:reload=1:expansion=none:fontcolor=white:fontsize=29:x=(245-text_w)/2:y=620,format=yuv420p[v]" \
  -map '[v]' -t 0.2 -f null -

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news strip tests passed.'

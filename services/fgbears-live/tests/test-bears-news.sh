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
grep -Fq 'drawbox=x=0:y=500:w=1280:h=78' "$ROOT/bin/start-stream.sh"
grep -Fq 'drawbox=x=0:y=578:w=1280:h=118' "$ROOT/bin/start-stream.sh"
grep -q '^BEARS_NEWS_FEED_URL=' "$ROOT/config/stream.env.example"

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

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news strip tests passed.'

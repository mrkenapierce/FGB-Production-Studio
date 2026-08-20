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

# Preserve the single-program-clock design. Bears news remains native drawtext
# over the advertising frame; the emoji-capable crawl arrives as one MJPEG lane.
if grep -Fq -- '-f rawvideo' "$ROOT/bin/start-stream.sh"; then
  echo 'Bears news must not use a rawvideo input; it can cause A/V pacing lag.' >&2
  exit 1
fi
if grep -Fq 'BEARS_NEWS_OVERLAY_PORT' "$ROOT/bin/start-stream.sh"; then
  echo 'The retired Bears news HTTP overlay must not be referenced.' >&2
  exit 1
fi
grep -q '^BEARS_NEWS_SCROLL_PPS=90$' "$ROOT/config/stream.env.example"
grep -q '^OUTPUT_FPS=24$' "$ROOT/config/stream.env.example"
grep -q '^VIDEO_GOP=48$' "$ROOT/config/stream.env.example"
grep -q '^DRAWTEXT_RELOAD_FRAMES=24$' "$ROOT/config/stream.env.example"

# shellcheck disable=SC2016
grep -Fq -- '-g "$VIDEO_GOP" -keyint_min "$VIDEO_GOP"' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq -- '-r "$OUTPUT_FPS" -fps_mode cfr -threads 0' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
if grep -Fq 'reload=1:' "$ROOT/bin/start-stream.sh"; then
  echo 'Dynamic drawtext must not reload files every video frame.' >&2
  exit 1
fi
# The crawl is rendered outside drawtext, so only news message + label reload.
# shellcheck disable=SC2016
reload_count=$(grep -oF 'reload=$DRAWTEXT_RELOAD_FRAMES' "$ROOT/bin/start-stream.sh" | wc -l)
[[ "$reload_count" -eq 2 ]] || {
  echo "Expected two one-second news drawtext reload controls, found $reload_count." >&2
  exit 1
}

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

# News text is physically cropped to the 990px message lane. The crawl renderer
# supplies its own complete 1280x139 lane and is composited at y=574.
grep -Fq 'split=2[base0][news0]' "$ROOT/bin/start-stream.sh"
grep -Fq '[news0]crop=w=990:h=68:x=267:y=23' "$ROOT/bin/start-stream.sh"
grep -Fq '[base][newslane]overlay=x=267:y=23:shortest=1' "$ROOT/bin/start-stream.sh"
grep -Fq '[withnews][2:v]overlay=x=0:y=574:shortest=1' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq 'x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\,text_w+990)' "$ROOT/bin/start-stream.sh"

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

# Parse and execute the exact production filter graph with synthetic base and
# crawl inputs. This validates the news crop plus external crawl composition.
python3 - "$ROOT/bin/start-stream.sh" "$TMP/runtime" <<'PY'
import re
import subprocess
import sys

script = open(sys.argv[1], encoding='utf-8').read()
runtime = sys.argv[2]
match = re.search(r'-filter_complex "(.*?)" \\\n', script, re.S)
assert match, 'production filter graph not found'
graph = match.group(1)
graph = graph.replace('[1:v]', '[BASE:v]', 1)
graph = graph.replace('[2:v]', '[1:v]')
graph = graph.replace('[BASE:v]', '[0:v]')
graph = graph.replace('$CRAWL_RUNTIME_DIR', runtime)
graph = graph.replace('$BEARS_NEWS_SCROLL_PPS', '90')
graph = graph.replace('$DRAWTEXT_RELOAD_FRAMES', '24')
subprocess.run([
    'ffmpeg', '-hide_banner', '-loglevel', 'error',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:r=24:d=0.4',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x139:r=15:d=0.4',
    '-filter_complex', graph, '-map', '[v]', '-t', '0.4', '-f', 'null', '-'
], check=True)
PY

kill "$PID"
wait "$PID" 2>/dev/null || true
PID=""

echo 'Bears news and emoji-crawl composition tests passed.'

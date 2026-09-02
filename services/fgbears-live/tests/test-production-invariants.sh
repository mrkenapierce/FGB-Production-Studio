#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
START="$ROOT/bin/start-stream.sh"
NEWS_BASE="$ROOT/bin/bears-news-feed.py"
NEWS_HQ="$ROOT/bin/bears-news-feed-hq.py"
CRAWL_HQ="$ROOT/bin/crawl-overlay-hq.py"
ENV_EXAMPLE="$ROOT/config/stream.env.example"

fail() { echo "PRODUCTION INVARIANT FAILED: $*" >&2; exit 1; }

# RULE 1 — Both moving text ribbons are rasterized before FFmpeg and run at the
# same 30-fps cadence as the finished program. Refreshed payloads may only swap
# at clean animation boundaries so neither ribbon jumps mid-pass.
grep -Fq 'BEARS_NEWS_SCROLL_PPS:=76' "$START" || fail 'RSS/news crawl speed must remain 76 px/s.'
grep -Fq 'BEARS_NEWS_SCROLL_PPS=76' "$ENV_EXAMPLE" || fail 'RSS/news default speed must remain 76 px/s.'
grep -Fq 'BEARS_NEWS_SCRIPT:=/opt/fgbears-live/bin/bears-news-feed-hq.py' "$START" || fail 'HQ deterministic RSS/news renderer must remain active.'
grep -Fq 'BEARS_NEWS_OVERLAY_PORT:=8789' "$START" || fail 'RSS/news dedicated overlay port must remain 8789.'
grep -Fq 'BEARS_NEWS_OVERLAY_FPS:=30' "$START" || fail 'RSS/news renderer must remain 30 fps to match the program clock.'
grep -Fq 'BEARS_NEWS_OVERLAY_PORT=8789' "$ENV_EXAMPLE" || fail 'RSS/news overlay port missing from environment defaults.'
grep -Fq 'BEARS_NEWS_OVERLAY_FPS=30' "$ENV_EXAMPLE" || fail 'RSS/news overlay FPS must remain 30 in environment defaults.'
grep -Fq 'CRAWL_OVERLAY_SCRIPT:=/opt/fgbears-live/bin/crawl-overlay-hq.py' "$START" || fail 'HQ deterministic lower crawl renderer must remain active.'
grep -Fq 'CRAWL_OVERLAY_FPS:=30' "$START" || fail 'Lower crawl renderer must remain 30 fps to match the program clock.'
grep -Fq 'CRAWL_OVERLAY_FPS=30' "$ENV_EXAMPLE" || fail 'Lower crawl overlay FPS must remain 30 in environment defaults.'
grep -Fq '"payloadSwap": "next-cycle-boundary"' "$NEWS_HQ" || fail 'RSS/news refreshed payloads must swap only at a scroll-cycle boundary.'
grep -Fq '"payloadSwap": "next-segment-boundary"' "$CRAWL_HQ" || fail 'Lower crawl refreshed payloads must swap only at a segment boundary.'
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.mjpg"' "$START" || fail 'FFmpeg must consume the dedicated Bears news MJPEG overlay.'
grep -Fq '[1:v][3:v]overlay=x=0:y=0:shortest=1[withnews]' "$START" || fail 'Bears news overlay is not composited in the upper ribbon.'
grep -Fq 'message_font = font(31, bold=True)' "$NEWS_BASE" || fail 'RSS/news message typography diverged from the canonical 31px bold treatment.'
grep -Fq 'label_font = font(29, bold=True)' "$NEWS_BASE" || fail 'RSS/news label typography diverged from the canonical 29px bold treatment.'

if grep -Fq 'textfile=$CRAWL_RUNTIME_DIR/bears-news-message.txt' "$START"; then
  fail 'RSS/news reintroduced FFmpeg drawtext, which can damage moving glyphs.'
fi
if grep -Fq '[news0]crop=' "$START"; then
  fail 'RSS/news reintroduced the retired FFmpeg crop lane.'
fi
if grep -Fq -- '-f rawvideo' "$START"; then
  fail 'RSS/news must use MJPEG rather than the retired rawvideo transport.'
fi

# RULE 2 — The shared master preserves already-mastered source audio exactly.
grep -Fq -- '-c:a copy' "$START" || fail 'Primary encoder must preserve source audio by stream copy.'
if grep -Fq -- '-af ' "$START"; then
  fail 'Live audio filters are forbidden in the primary encoder.'
fi
grep -Fq 'YOUTUBE_AUDIO_SAMPLE_RATE=48000' "$ENV_EXAMPLE" || fail 'YouTube transport documentation/defaults must match native 48 kHz program audio.'

# RULE 3 — Retired X and Instagram transport targets stay removed.
if grep -Fq 'X local mirror' "$START" || grep -Fq 'Instagram local mirror' "$START"; then
  fail 'Social sidecar tee outputs are forbidden in the primary encoder.'
fi

echo 'FGB production invariants: PASS'

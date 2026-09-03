#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
START="$ROOT/bin/start-stream.sh"
NEWS="$ROOT/bin/bears-news-feed.py"
ENV_EXAMPLE="$ROOT/config/stream.env.example"
INSTALL="$ROOT/bin/install.sh"

fail() { echo "PRODUCTION INVARIANT FAILED: $*" >&2; exit 1; }

# RULE 1 — Bears news is rasterized before FFmpeg and cadence-matched to the
# 30 fps master so horizontal motion does not exhibit deterministic judder.
grep -Fq 'BEARS_NEWS_SCROLL_PPS:=76' "$START" || fail 'RSS/news crawl speed must remain 76 px/s.'
grep -Fq 'BEARS_NEWS_SCROLL_PPS=76' "$ENV_EXAMPLE" || fail 'RSS/news default speed must remain 76 px/s.'
grep -Fq 'BEARS_NEWS_OVERLAY_PORT:=8789' "$START" || fail 'RSS/news dedicated overlay port must remain 8789.'
grep -Fq 'BEARS_NEWS_OVERLAY_FPS:=30' "$START" || fail 'RSS/news image renderer must remain cadence-matched at 30 fps.'
grep -Fq 'BEARS_NEWS_OVERLAY_PORT=8789' "$ENV_EXAMPLE" || fail 'RSS/news overlay port missing from environment defaults.'
grep -Fq 'BEARS_NEWS_OVERLAY_FPS=30' "$ENV_EXAMPLE" || fail 'RSS/news overlay FPS must default to 30.'
grep -Fq "'BEARS_NEWS_OVERLAY_FPS':'30'" "$INSTALL" || fail 'Installer must preserve the 30 fps news overlay setting.'
if grep -Fqw 'python3-qrcode' "$INSTALL"; then
  fail 'Installer must not require unused python3-qrcode; QR rendering uses qrencode.'
fi
grep -Fq 'apt_get_with_retry' "$INSTALL" || fail 'Installer must retain bounded apt retry handling.'
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.mjpg"' "$START" || fail 'FFmpeg must consume the dedicated Bears news MJPEG overlay.'
grep -Fq '[1:v][3:v]overlay=x=0:y=0:shortest=1[withnews]' "$START" || fail 'Bears news overlay is not composited in the upper ribbon.'
grep -Fq 'message_font = font(31, bold=True)' "$NEWS" || fail 'RSS/news message typography diverged from the canonical 31px bold treatment.'
grep -Fq 'label_font = font(29, bold=True)' "$NEWS" || fail 'RSS/news label typography diverged from the canonical 29px bold treatment.'

if grep -Fq 'textfile=$CRAWL_RUNTIME_DIR/bears-news-message.txt' "$START"; then
  fail 'RSS/news reintroduced FFmpeg drawtext, which can damage moving glyphs.'
fi
if grep -Fq '[news0]crop=' "$START"; then
  fail 'RSS/news reintroduced the retired FFmpeg crop lane.'
fi
if grep -Fq -- '-f rawvideo' "$START"; then
  fail 'RSS/news must use MJPEG rather than the retired rawvideo transport.'
fi

# RULE 2 — The primary encoder copies source audio without live DSP.
grep -Fq -- '-c:a copy' "$START" || fail 'Primary encoder must preserve source audio by stream copy.'
if grep -Fq -- '-af ' "$START"; then
  fail 'Live audio filters are forbidden in the primary encoder.'
fi

# RULE 3 — Retired X and Instagram transport targets stay removed.
if grep -Fq 'X local mirror' "$START" || grep -Fq 'Instagram local mirror' "$START"; then
  fail 'Social sidecar tee outputs are forbidden in the primary encoder.'
fi

echo 'FGB production invariants: PASS'

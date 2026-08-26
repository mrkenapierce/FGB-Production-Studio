#!/usr/bin/env bash
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
START="$ROOT/bin/start-stream.sh"
INSTALL="$ROOT/bin/install.sh"
ENV_EXAMPLE="$ROOT/config/stream.env.example"

fail() { echo "PRODUCTION INVARIANT FAILED: $*" >&2; exit 1; }

# RULE 1 — Main Crawl is the visual/motion exemplar for RSS/news.
# Canonical normal crawl speed after the approved 28% slowdown is 76 px/s.
grep -Fq 'BEARS_NEWS_SCROLL_PPS:=76' "$START" || fail 'RSS/news crawl speed must match Main Crawl canonical speed (76 px/s).'
grep -Fq 'BEARS_NEWS_SCROLL_PPS=76' "$ENV_EXAMPLE" || fail 'RSS/news default speed must remain 76 px/s.'

# Typography and clean single-divider treatment must stay aligned with Main Crawl.
grep -Fq 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS' "$START" || fail 'RSS/news message typography/motion geometry diverged from Main Crawl.'
grep -Fq 'fontcolor=white:fontsize=29:x=18+(239-text_w)/2:y=39' "$START" || fail 'RSS/news label typography diverged from Main Crawl.'
if grep -Fq 'drawbox=x=257:y=23:w=5:h=68:color=0x0B162A' "$START"; then
  fail 'RSS/news crawl reintroduced the old double-divider/notch treatment.'
fi

if grep -Fq 'crop=w=970:h=68:x=277:y=23' "$START"; then
  fail 'RSS/news crawl reintroduced the obsolete internal blue clipping gutter.'
fi

# RULE 2 — Audio is immutable at runtime.
grep -Fq "CANONICAL_AUDIO_FILTER='volume=-2dB,aresample=48000:first_pts=0'" "$START" || fail 'Canonical live audio filter changed.'
grep -Fq -- '-af "$CANONICAL_AUDIO_FILTER"' "$START" || fail 'FFmpeg must use the canonical immutable audio filter.'
if grep -Fq -- '-af "$PODCAST_AUDIO_FILTER"' "$START"; then
  fail 'Live audio may not be overridden by stream.env.'
fi

# No destructive or time-warping live DSP may be injected by installer/runtime defaults.
if grep -Eqi 'loudnorm=|acompressor=|highpass=|afftdn=|deesser=|equalizer=|aresample=[^[:space:]]*async=1' "$START" "$INSTALL" "$ENV_EXAMPLE"; then
  fail 'Destructive/time-warping live audio DSP is forbidden.'
fi

grep -Fq '"PODCAST_AUDIO_FILTER": "volume=-2dB,aresample=48000:first_pts=0"' "$INSTALL" || fail 'Installer must preserve the canonical audio rule.'

# RULE 3 — YouTube is the only production transport target.
if grep -Fq 'X local mirror' "$START" || grep -Fq 'Instagram local mirror' "$START"; then
  fail 'Social sidecar tee outputs are forbidden in the primary encoder.'
fi

echo 'FGB production invariants: PASS'

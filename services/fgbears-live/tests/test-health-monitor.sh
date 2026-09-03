#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORKFLOW="$ROOT/../../.github/workflows/fgbears-live-monitor.yml"
HEALTH="$ROOT/bin/healthcheck.sh"
TIMER="$ROOT/systemd/fgbears-live-health.timer"
INSTALL="$ROOT/bin/install.sh"

bash -n "$HEALTH"

grep -Fq 'YOUTUBE_SERVICE=${YOUTUBE_SERVICE:-fgbears-youtube-v2.service}' "$HEALTH"
grep -Fq 'recover_youtube_v2()' "$HEALTH"
grep -Fq 'systemctl restart "$YOUTUBE_SERVICE"' "$HEALTH"
grep -Fq 'systemctl restart fgbears-live.service' "$HEALTH"
if grep -Eq 'YOUTUBE_RELAY_SERVICE|recover_youtube_relay|fgbears-youtube-relay.service|lovable-compositor|audio-watchdog' "$HEALTH"; then
  echo 'Healthcheck contains retired YouTube supervision.' >&2; exit 1
fi

# The isolated v2 recovery function must never restart master or Rumble.
python3 - "$HEALTH" <<'PY'
from pathlib import Path
import re, sys
text=Path(sys.argv[1]).read_text()
m=re.search(r'recover_youtube_v2\(\) \{(.*?)\n\}', text, re.S)
assert m, 'recover_youtube_v2 function missing'
body=m.group(1)
assert 'systemctl restart "$YOUTUBE_SERVICE"' in body
assert 'fgbears-live.service' not in body
assert 'fgbears-rumble' not in body
PY

# Host health cadence stays five minutes; public GitHub audit cadence is 15.
grep -Eq 'OnCalendar=.*0/5|OnUnitActiveSec=5min' "$TIMER"
grep -Fq "cron: '*/15 * * * *'" "$WORKFLOW"

grep -Fq 'fgbears-youtube-v2.service' "$WORKFLOW"
grep -Fq 'fgbears-rumble-relay.service' "$WORKFLOW"
grep -Fq 'fgbears-live.service' "$WORKFLOW"
grep -Fq 'legacy=masked' "$WORKFLOW"

# The scheduled monitor may NAME retired units only to verify they remain
# inactive and masked. It must never mutate them or treat a retired endpoint as
# an active production dependency.
if grep -Eq 'YOUTUBE_RELAY_SERVICE|:8791' "$WORKFLOW"; then
  echo 'Scheduled monitor still depends on a retired runtime pathway.' >&2; exit 1
fi
if grep -Eq 'systemctl[[:space:]]+(restart|start|stop|enable|disable|mask|unmask)' "$WORKFLOW"; then
  echo 'Scheduled monitor is not read-only.' >&2; exit 1
fi

grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$INSTALL"

echo 'Health supervision tests passed: shared master + isolated YouTube v2.'

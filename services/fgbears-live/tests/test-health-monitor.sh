#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORKFLOW="$ROOT/../../.github/workflows/fgbears-live-monitor.yml"
HEALTH="$ROOT/bin/healthcheck.sh"
TIMER="$ROOT/systemd/fgbears-live-health.timer"
INSTALL="$ROOT/bin/install.sh"

bash -n "$HEALTH"
grep -Fq 'YOUTUBE_SERVICE=${YOUTUBE_SERVICE:-fgbears-youtube-v3.service}' "$HEALTH"
grep -Fq 'YOUTUBE_PROGRESS_FILE=${YOUTUBE_PROGRESS_FILE:-/run/fgbears-youtube-v3/ffmpeg-progress.log}' "$HEALTH"
grep -Fq 'recover_youtube_v3()' "$HEALTH"
grep -Fq 'check_youtube_v3_pacing()' "$HEALTH"
grep -Fq 'systemctl restart "$YOUTUBE_SERVICE"' "$HEALTH"
grep -Fq 'systemctl restart fgbears-live.service' "$HEALTH"
if grep -Eq 'YOUTUBE_RELAY_SERVICE|recover_youtube_relay|lovable-compositor|audio-watchdog' "$HEALTH"; then echo 'Healthcheck contains retired YouTube supervision.' >&2; exit 1; fi

python3 - "$HEALTH" <<'PY'
from pathlib import Path
import re,sys
text=Path(sys.argv[1]).read_text()
m=re.search(r'recover_youtube_v3\(\) \{(.*?)\n\}',text,re.S); assert m
body=m.group(1)
assert 'systemctl restart "$YOUTUBE_SERVICE"' in body
assert 'fgbears-live.service' not in body
assert 'fgbears-rumble' not in body
m=re.search(r'check_youtube_v3_pacing\(\) \{(.*?)\n\}',text,re.S); assert m
body=m.group(1)
assert 'Circular buffer overrun' in body
assert 'systemctl restart' not in body
PY

grep -Eq 'OnCalendar=.*0/5|OnUnitActiveSec=5min' "$TIMER"
grep -Fq "cron: '*/15 * * * *'" "$WORKFLOW"
grep -Fq 'fgbears-youtube-v3.service' "$WORKFLOW"
grep -Fq 'fgbears-youtube-v2.service' "$WORKFLOW"
grep -Fq 'YOUTUBE_UDP_OVERRUN' "$WORKFLOW"
grep -Fq 'youtube_speed=' "$WORKFLOW"
grep -Fq 'cpu_pressure_avg10=' "$WORKFLOW"
if grep -Eq 'YOUTUBE_RELAY_SERVICE|:8791' "$WORKFLOW"; then echo 'Scheduled monitor depends on retired runtime.' >&2; exit 1; fi
if grep -Eq 'systemctl[[:space:]]+(restart|start|stop|enable|disable|mask|unmask)' "$WORKFLOW"; then echo 'Scheduled monitor is not read-only.' >&2; exit 1; fi

grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$INSTALL"
grep -Fq 'fgbears-youtube-v3.service' "$INSTALL"
! grep -Fq 'systemctl enable fgbears-youtube-v2.service' "$INSTALL"

echo 'Health supervision tests passed: shared master + isolated YouTube v3 pacing telemetry.'

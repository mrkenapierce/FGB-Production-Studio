#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
WORKFLOW="$ROOT/../../.github/workflows/fgbears-live-monitor.yml"
HEALTH="$ROOT/bin/healthcheck.sh"
TIMER="$ROOT/systemd/fgbears-live-health.timer"
INSTALL="$ROOT/bin/install.sh"
CACHE_UNIT="$ROOT/youtube-v3/fgbears-lovable-state-cache.service"
YOUTUBE_UNIT="$ROOT/youtube-v3/fgbears-youtube-v3.service"

bash -n "$HEALTH"
grep -Fq 'YOUTUBE_GENERATION_FILE=/etc/fgbears-live/youtube-generation' "$HEALTH"
grep -Fq 'YOUTUBE_V3_SERVICE=fgbears-youtube-v3.service' "$HEALTH"
grep -Fq 'YOUTUBE_V3_PROGRESS_FILE=/run/fgbears-youtube-v3/ffmpeg-progress.log' "$HEALTH"
! grep -Fq 'YOUTUBE_SERVICE=${YOUTUBE_SERVICE:-' "$HEALTH"
grep -Fq 'recover_youtube_destination()' "$HEALTH"
grep -Fq 'check_youtube_v3_pacing()' "$HEALTH"
grep -Fq 'systemctl restart "$service"' "$HEALTH"
grep -Fq 'systemctl restart fgbears-live.service' "$HEALTH"
if grep -Eq 'YOUTUBE_RELAY_SERVICE|recover_youtube_relay|lovable-compositor|audio-watchdog' "$HEALTH"; then echo 'Healthcheck contains retired YouTube supervision.' >&2; exit 1; fi

python3 - "$HEALTH" <<'PY'
from pathlib import Path
import re,sys
text=Path(sys.argv[1]).read_text()
assert 'YOUTUBE_V3_SERVICE=fgbears-youtube-v3.service' in text
m=re.search(r'recover_youtube_destination\(\) \{(.*?)\n\}',text,re.S); assert m
body=m.group(1)
assert 'systemctl restart "$service"' in body
assert 'fgbears-live.service' not in body
assert 'fgbears-rumble' not in body
m=re.search(r'check_youtube_v3_pacing\(\) \{(.*?)\n\}',text,re.S); assert m
body=m.group(1)
assert 'Circular buffer overrun' in body
assert 'systemctl restart' not in body
PY

grep -Eq 'OnCalendar=.*0/5|OnUnitActiveSec=5min' "$TIMER"
grep -Fq "cron: '*/15 * * * *'" "$WORKFLOW"
grep -Fq 'CACHE=fgbears-lovable-state-cache.service' "$WORKFLOW"
grep -Fq 'CONTROL_STATE=/run/fgbears-control-plane/stream-state.json' "$WORKFLOW"
grep -Fq 'CONTROL_HEALTH=/run/fgbears-control-plane/cache-health.json' "$WORKFLOW"
grep -Fq "fgb-stream-state/v1" "$WORKFLOW"
grep -Fq 'rendersRealQuestion' "$WORKFLOW"
grep -Fq 'yt_rumble_trivia_redirect' "$WORKFLOW"
grep -Fq 'YOUTUBE_UDP_OVERRUN' "$WORKFLOW"
grep -Fq 'youtube_steady_rate=' "$WORKFLOW"
grep -Fq 'cpu_pressure_avg10=' "$WORKFLOW"
if grep -Eq 'overlay-state\.json|YOUTUBE_RELAY_SERVICE|:8791' "$WORKFLOW"; then echo 'Scheduled monitor depends on retired runtime/state.' >&2; exit 1; fi
if grep -Eq 'systemctl[[:space:]]+(restart|start|stop|enable|disable|mask|unmask)' "$WORKFLOW"; then echo 'Scheduled monitor is not read-only.' >&2; exit 1; fi

grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$INSTALL"
grep -Fq 'fgbears-lovable-state-cache.service' "$INSTALL"
grep -Fq 'fgbears-youtube-v3.service' "$INSTALL"
! grep -Fq 'systemctl enable fgbears-youtube-v2.service' "$INSTALL"
grep -Fq 'RuntimeDirectory=fgbears-control-plane' "$CACHE_UNIT"
grep -Fq 'Wants=network-online.target fgbears-lovable-state-cache.service' "$YOUTUBE_UNIT"
! grep -Fq 'Requires=fgbears-lovable-state-cache.service' "$YOUTUBE_UNIT"

echo 'Health supervision tests passed: Lovable cache + isolated YouTube v3 + untouched master/Rumble.'

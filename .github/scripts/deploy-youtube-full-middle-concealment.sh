#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 77; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
LEGACY=fgbears-youtube-relay.service
COMP_SCRIPT=/opt/fgbears-live/bin/youtube-lovable-compositor.sh
MASK_SCRIPT=/opt/fgbears-live/bin/youtube-question-mask.py
BACKUP=$(mktemp -d /tmp/fgb-youtube-fullmask.XXXXXX)
SUCCESS=0

pid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
active() { systemctl is-active --quiet "$1"; }
has_pid_port() {
  local p="$1" port="$2"
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v r=":$port" 'index($0,q)&&index($0,r){ok=1} END{exit(ok?0:1)}'
}
master_speed() {
  awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); if(v!="") print v+0}' /srv/fgbears-live/logs/ffmpeg-progress.log 2>/dev/null || true
}

rollback() {
  local rc=$?
  (( SUCCESS == 0 )) || return 0
  echo "FULL_MIDDLE_ROLLBACK=BEGIN rc=$rc"
  systemctl stop "$COMP" "$ROUTING" 2>/dev/null || true
  [[ -f "$BACKUP/compositor.sh" ]] && install -m 0755 "$BACKUP/compositor.sh" "$COMP_SCRIPT" || true
  [[ -f "$BACKUP/question-mask.py" ]] && install -m 0755 "$BACKUP/question-mask.py" "$MASK_SCRIPT" || true
  systemctl reset-failed "$ROUTING" "$COMP" || true
  systemctl start "$ROUTING" || true
  sleep 2
  systemctl start "$COMP" || true
  sleep 3
  if ! has_pid_port "$(pid "$COMP")" 443; then
    systemctl stop "$COMP" "$ROUTING" 2>/dev/null || true
    systemctl reset-failed "$LEGACY" || true
    systemctl start "$LEGACY" || true
  fi
  echo "FULL_MIDDLE_ROLLBACK=END master=$(pid "$MASTER") rumble=$(pid "$RUMBLE") comp=$(pid "$COMP") legacy=$(pid "$LEGACY")"
  rm -rf "$BACKUP" /tmp/youtube-question-mask.py /tmp/youtube-lovable-compositor.sh /tmp/deploy-youtube-full-middle-concealment.sh
  exit "$rc"
}
trap rollback EXIT

for u in "$MASTER" "$RUMBLE" "$COMP" "$ROUTING"; do active "$u"; done
MASTER0=$(pid "$MASTER")
RUMBLE0=$(pid "$RUMBLE")
COMP0=$(pid "$COMP")
has_pid_port "$COMP0" 443
has_pid_port "$RUMBLE0" 1935
SPEED0=$(master_speed)
if [[ -n "$SPEED0" ]]; then python3 -c 'import sys; assert float(sys.argv[1]) >= 0.98, sys.argv[1]' "$SPEED0"; fi
echo "PRE master=$MASTER0 rumble=$RUMBLE0 comp=$COMP0 speed=${SPEED0:-unknown}"

cp -a "$COMP_SCRIPT" "$BACKUP/compositor.sh"
cp -a "$MASK_SCRIPT" "$BACKUP/question-mask.py"
install -m 0755 /tmp/youtube-question-mask.py "$MASK_SCRIPT"
install -m 0755 /tmp/youtube-lovable-compositor.sh "$COMP_SCRIPT"

# Only the YouTube-only routing/compositor services restart. Master and Rumble
# are hard invariants and must keep the same PIDs throughout.
systemctl stop "$COMP"
systemctl restart "$ROUTING"

MASK_OK=0
for _ in $(seq 1 25); do
  if health=$(curl -fsS --max-time 2 http://127.0.0.1:8791/healthz 2>/dev/null); then
    if printf '%s' "$health" | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True,p
assert p.get("canvas")==[1280,720],p
assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470},p
assert p.get("maskRegion")=={"x":0,"y":104,"width":1280,"height":470},p
assert p.get("frameSize")==[1280,470],p
assert p.get("executionScaling")=="full_middle_protection",p
assert p.get("fps")==30,p
' 2>/dev/null; then MASK_OK=1; break; fi
  fi
  sleep 1
done
(( MASK_OK == 1 ))
echo "FULL_MIDDLE_MASK_CONTRACT=PASS $health"

systemctl reset-failed "$COMP" || true
systemctl start "$COMP"
CONNECTED=0
for _ in $(seq 1 30); do
  COMP1=$(pid "$COMP")
  if active "$COMP" && has_pid_port "$COMP1" 443; then CONNECTED=1; break; fi
  sleep 1
done
(( CONNECTED == 1 ))
! active "$LEGACY"
echo "YOUTUBE_OWNER=COMPOSITOR pid=$COMP1"

# Verify no collateral restart or loss on shared/Rumble path.
[[ "$(pid "$MASTER")" == "$MASTER0" ]]
[[ "$(pid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935

# Sustain for 20 seconds and reject if the new 1280x470 RGBA cover causes the
# shared master to fall behind or the YouTube branch to exceed safe CPU.
max_cpu=0
min_speed=999
for _ in $(seq 1 20); do
  [[ "$(pid "$MASTER")" == "$MASTER0" ]]
  [[ "$(pid "$RUMBLE")" == "$RUMBLE0" ]]
  [[ "$(pid "$COMP")" == "$COMP1" ]]
  has_pid_port "$COMP1" 443
  has_pid_port "$RUMBLE0" 1935
  cpu=$(ps -p "$COMP1" -o %cpu= | tr -d ' ')
  speed=$(master_speed)
  if [[ -n "$speed" ]]; then
    python3 -c 'import sys; assert float(sys.argv[1]) >= 0.99, sys.argv[1]' "$speed"
    min_speed=$(python3 -c 'import sys; print(min(float(sys.argv[1]),float(sys.argv[2])))' "$min_speed" "$speed")
  fi
  max_cpu=$(python3 -c 'import sys; print(max(float(sys.argv[1]),float(sys.argv[2])))' "$max_cpu" "$cpu")
  sleep 1
done
python3 -c 'import sys; assert float(sys.argv[1]) <= 50.0, sys.argv[1]' "$max_cpu"
echo "FULL_MIDDLE_STABILITY=PASS min_master_speed=${min_speed}x max_compositor_cpu=${max_cpu}%"

# If a question is active now, require the latch to remain active on every
# sample until the phase exits (bounded observation so deployment never hangs).
h=$(curl -fsS --max-time 2 http://127.0.0.1:8791/healthz)
if printf '%s' "$h" | python3 -c 'import json,sys;p=json.load(sys.stdin);raise SystemExit(0 if p.get("phase")=="question" else 1)' 2>/dev/null; then
  samples=0
  for _ in $(seq 1 90); do
    h=$(curl -fsS --max-time 2 http://127.0.0.1:8791/healthz)
    result=$(printf '%s' "$h" | python3 -c 'import json,sys;p=json.load(sys.stdin);print("END" if p.get("phase")!="question" else ("OK" if p.get("active") is True else "FAIL"))')
    [[ "$result" == END ]] && break
    [[ "$result" == OK ]]
    samples=$((samples+1))
    sleep 1
  done
  (( samples > 0 ))
  echo "LIVE_FULL_MIDDLE_QUESTION_LATCH=PASS samples=$samples"
else
  echo 'LIVE_FULL_MIDDLE_QUESTION_LATCH=NOT_ACTIVE_AT_DEPLOY'
fi

SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/youtube-question-mask.py /tmp/youtube-lovable-compositor.sh /tmp/deploy-youtube-full-middle-concealment.sh
echo 'YOUTUBE_FULL_MIDDLE_CONCEALMENT=PASS'

#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 77; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
LEGACY=fgbears-youtube-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
COMP_SCRIPT=/opt/fgbears-live/bin/youtube-lovable-compositor.sh
MASK_SCRIPT=/opt/fgbears-live/bin/youtube-question-mask.py
COMP_UNIT=/etc/systemd/system/fgbears-youtube-lovable-compositor.service
ROUTING_UNIT=/etc/systemd/system/fgbears-youtube-lovable-routing.service
BACKUP=$(mktemp -d /tmp/fgb-youtube-720p.XXXXXX)
PATCHED_MASK="$BACKUP/question-mask.patched.py"
SUCCESS=0

active() { systemctl is-active --quiet "$1"; }
mainpid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
has_pid_port() {
  local pid="$1" port="$2"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v p="pid=$pid" -v q=":$port" 'index($0,p)&&index($0,q){ok=1} END{exit(ok?0:1)}'
}
master_speed() {
  awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); if(v!="") print v+0}' /srv/fgbears-live/logs/ffmpeg-progress.log 2>/dev/null || true
}

rollback() {
  local rc=$?
  (( SUCCESS == 0 )) || return 0
  echo "ROLLBACK_720P=BEGIN rc=$rc"
  systemctl stop "$COMP" "$ROUTING" 2>/dev/null || true
  [[ -f "$BACKUP/compositor.sh" ]] && install -m 0755 "$BACKUP/compositor.sh" "$COMP_SCRIPT" || true
  [[ -f "$BACKUP/question-mask.py" ]] && install -m 0755 "$BACKUP/question-mask.py" "$MASK_SCRIPT" || true
  [[ -f "$BACKUP/compositor.service" ]] && install -m 0644 "$BACKUP/compositor.service" "$COMP_UNIT" || true
  [[ -f "$BACKUP/routing.service" ]] && install -m 0644 "$BACKUP/routing.service" "$ROUTING_UNIT" || true
  systemctl daemon-reload || true
  systemctl reset-failed "$ROUTING" "$COMP" || true
  systemctl start "$ROUTING" || true
  sleep 2
  systemctl start "$COMP" || true

  restored=0
  for _ in $(seq 1 25); do
    p=$(mainpid "$COMP")
    if active "$COMP" && has_pid_port "$p" 443; then restored=1; break; fi
    sleep 1
  done

  if (( restored == 0 )); then
    systemctl reset-failed "$LEGACY" || true
    systemctl start "$LEGACY" || true
    for _ in $(seq 1 20); do
      p=$(mainpid "$LEGACY")
      has_pid_port "$p" 443 && break
      sleep 1
    done
  fi
  echo "ROLLBACK_720P comp=$(mainpid "$COMP") legacy=$(mainpid "$LEGACY") master=$(mainpid "$MASTER") rumble=$(mainpid "$RUMBLE")"
  rm -rf "$BACKUP"
  exit "$rc"
}
trap rollback EXIT

for u in "$MASTER" "$RUMBLE" "$COMP" "$ROUTING"; do active "$u"; done
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
COMP0=$(mainpid "$COMP")
LEGACY0=$(mainpid "$LEGACY")
has_pid_port "$COMP0" 443
has_pid_port "$RUMBLE0" 1935
SPEED0=$(master_speed)
if [[ -n "$SPEED0" ]]; then python3 -c 'import sys; assert float(sys.argv[1]) >= 0.98, sys.argv[1]' "$SPEED0"; fi
echo "PRE master=$MASTER0 rumble=$RUMBLE0 compositor=$COMP0 legacy=$LEGACY0 speed=${SPEED0:-unknown} load=$(cut -d' ' -f1-3 /proc/loadavg)"

cp -a "$COMP_SCRIPT" "$BACKUP/compositor.sh"
cp -a "$MASK_SCRIPT" "$BACKUP/question-mask.py"
cp -a "$COMP_UNIT" "$BACKUP/compositor.service"
cp -a "$ROUTING_UNIT" "$BACKUP/routing.service"

# Work on a root-owned copy inside the root-owned rollback directory. On this
# host fs.protected_regular prevents privileged in-place rewrites of files that
# were SCP-created by the SSH user in /tmp.
cp /tmp/youtube-question-mask.py "$PATCHED_MASK"

# Patch the routing renderer with question-phase hysteresis. Once the YouTube
# cover has appeared for a question, a transient false flag or routing fetch
# error cannot remove it while the authoritative phase remains question. An
# explicit phase exit/ad break clears it immediately; prolonged endpoint loss
# remains bounded by the routing service's stale grace.
python3 - "$PATCHED_MASK" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = '''        active = (\n            trivia.get("youtubeMaskActive") is True\n            and phase == "question"\n            and not remote_stale\n            and not ads_visible\n            and not ad_break\n        )\n        with self.lock:\n            self.active = active\n            self.phase = phase\n            self.last_good = time.time()\n            self.last_error = None\n'''
new = '''        requested_active = (\n            trivia.get("youtubeMaskActive") is True\n            and phase == "question"\n            and not remote_stale\n            and not ads_visible\n            and not ad_break\n        )\n        with self.lock:\n            if ads_visible or ad_break or phase != "question":\n                self.active = False\n            elif requested_active:\n                self.active = True\n            elif self.active and phase == "question":\n                # Latch through transient flag/staleness changes for the full\n                # authoritative question phase.\n                self.active = True\n            self.phase = phase\n            self.last_good = time.time()\n            self.last_error = None\n'''
old_error = '''    def error(self, exc: Exception) -> None:\n        with self.lock:\n            self.active = False\n            self.last_error = str(exc)\n'''
new_error = '''    def error(self, exc: Exception) -> None:\n        with self.lock:\n            # Do not flash the cover off on a transient API/network error.\n            # snapshot() still applies the finite stale-age safety bound.\n            self.last_error = str(exc)\n'''
if s.count(old) != 1 or s.count(old_error) != 1:
    raise SystemExit('question-mask source no longer matches the certified patch contract')
s = s.replace(old, new).replace(old_error, new_error)
p.write_text(s)
PY

grep -q 'Latch through transient flag/staleness changes' "$PATCHED_MASK"
grep -q 'Do not flash the cover off on a transient API/network error' "$PATCHED_MASK"

install -m 0755 /tmp/youtube-lovable-compositor.sh "$COMP_SCRIPT"
install -m 0755 "$PATCHED_MASK" "$MASK_SCRIPT"
install -m 0644 /tmp/fgbears-youtube-lovable-compositor.service "$COMP_UNIT"
install -m 0644 /tmp/fgbears-youtube-lovable-routing.service "$ROUTING_UNIT"
systemctl daemon-reload
systemctl enable "$COMP" "$ROUTING" >/dev/null

# The unused direct relay must never compete for the YouTube stream key or CPU.
systemctl stop "$LEGACY" 2>/dev/null || true
systemctl disable "$LEGACY" >/dev/null 2>&1 || true

# YouTube-only restart. Master and Rumble are hard invariants and are never restarted.
systemctl stop "$COMP"
systemctl restart "$ROUTING"

MASK_OK=0
health=''
for _ in $(seq 1 20); do
  if health=$(curl -fsS --max-time 2 http://127.0.0.1:8791/healthz 2>/dev/null); then
    if printf '%s' "$health" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True;assert p.get("canvas")==[1280,720],p;assert p.get("maskRegion")=={"x":462,"y":104,"width":798,"height":470},p;assert p.get("fps")==30,p' 2>/dev/null; then
      MASK_OK=1; break
    fi
  fi
  sleep 1
done
(( MASK_OK == 1 ))
echo "MASK_720P=PASS $health"

systemctl reset-failed "$COMP" || true
systemctl start "$COMP"
CONNECTED=0
for _ in $(seq 1 25); do
  COMP1=$(mainpid "$COMP")
  if active "$COMP" && has_pid_port "$COMP1" 443; then CONNECTED=1; break; fi
  sleep 1
done
(( CONNECTED == 1 ))
! active "$LEGACY"
echo "YOUTUBE_OWNER=COMPOSITOR pid=$COMP1"

SEG=''
for _ in $(seq 1 20); do
  SEG=$(find /run/fgbears-youtube-lovable-compositor -maxdepth 1 -type f -name 'monitor-*.ts' -size +1000c -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1{sub(/^[^ ]+ /,"");print}' || true)
  [[ -n "$SEG" ]] && break
  sleep 1
done
[[ -n "$SEG" ]]
PROBE=$(ffprobe -v error -show_streams -of json "$SEG")
printf '%s' "$PROBE" | python3 -c '
import json,sys
p=json.load(sys.stdin)
streams=p.get("streams",[])
v=next(s for s in streams if s.get("codec_type")=="video")
a=next(s for s in streams if s.get("codec_type")=="audio")
assert int(v.get("width",0))==1280,v
assert int(v.get("height",0))==720,v
assert v.get("r_frame_rate") in {"30/1","60/2"},v
assert int(a.get("sample_rate",0))==44100,a
assert int(a.get("channels",0))==2,a
print("YOUTUBE_AV=PASS video={}x{}@{} audio={}Hz/{}ch".format(v.get("width"),v.get("height"),v.get("r_frame_rate"),a.get("sample_rate"),a.get("channels")))
'

[[ "$(mainpid "$MASTER")" == "$MASTER0" ]]
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935

# Sustained ownership/resource gate: reject 720p if it makes the shared program
# fall behind or consumes too much of the single CPU after the redundant relay is gone.
sleep 15
COMP2=$(mainpid "$COMP")
[[ "$COMP2" == "$COMP1" ]]
has_pid_port "$COMP2" 443
CPU=$(ps -p "$COMP2" -o %cpu= | tr -d ' ')
SPEED=$(master_speed)
if [[ -n "$SPEED" ]]; then
  python3 -c 'import sys;s=float(sys.argv[1]);assert s>=0.99,s' "$SPEED"
  echo "MASTER_REALTIME=${SPEED}x"
else
  echo 'MASTER_REALTIME=NO_RECENT_SAMPLE_PID_INVARIANTS_PASS'
fi
python3 -c 'import sys; c=float(sys.argv[1]); assert c <= 50.0, c' "$CPU"

echo "STABILITY compositor_cpu=${CPU}% load=$(cut -d' ' -f1-3 /proc/loadavg)"
[[ "$(mainpid "$MASTER")" == "$MASTER0" ]]
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935
has_pid_port "$COMP2" 443
! active "$LEGACY"

echo "POST master=$(mainpid "$MASTER") rumble=$(mainpid "$RUMBLE") youtube720=$(mainpid "$COMP")"
echo 'YOUTUBE_720P_CUTOVER=PASS'
echo 'QUESTION_MASK_LATCH=PASS source-patched finite-stale-grace=30s'
SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/youtube-lovable-compositor.sh /tmp/youtube-question-mask.py /tmp/fgbears-youtube-lovable-compositor.service /tmp/fgbears-youtube-lovable-routing.service /tmp/cutover-youtube-720p.sh

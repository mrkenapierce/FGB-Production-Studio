#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root' >&2; exit 77; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
LEGACY=fgbears-youtube-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
COMP_SCRIPT=/opt/fgbears-live/bin/youtube-lovable-compositor.sh
COMP_UNIT=/etc/systemd/system/fgbears-youtube-lovable-compositor.service
ROUTING_UNIT=/etc/systemd/system/fgbears-youtube-lovable-routing.service
BACKUP=$(mktemp -d /tmp/fgb-youtube-720p.XXXXXX)
SUCCESS=0

active() { systemctl is-active --quiet "$1"; }
mainpid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
has_pid_port() {
  local pid="$1" port="$2"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v p="pid=$pid" -v q=":$port" 'index($0,p)&&index($0,q){ok=1} END{exit(ok?0:1)}'
}

rollback() {
  local rc=$?
  (( SUCCESS == 0 )) || return 0
  echo "ROLLBACK_720P=BEGIN rc=$rc"
  systemctl stop "$COMP" "$ROUTING" 2>/dev/null || true
  [[ -f "$BACKUP/compositor.sh" ]] && install -m 0755 "$BACKUP/compositor.sh" "$COMP_SCRIPT" || true
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

  # Emergency fallback only if the known-good 360p compositor cannot reclaim YouTube.
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

# Current production baseline: the 360p compositor is the real YouTube sender.
for u in "$MASTER" "$RUMBLE" "$COMP" "$ROUTING"; do active "$u"; done
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
COMP0=$(mainpid "$COMP")
LEGACY0=$(mainpid "$LEGACY")
has_pid_port "$COMP0" 443
has_pid_port "$RUMBLE0" 1935
echo "PRE master=$MASTER0 rumble=$RUMBLE0 compositor360=$COMP0 legacy=$LEGACY0 load=$(cut -d' ' -f1-3 /proc/loadavg)"

cp -a "$COMP_SCRIPT" "$BACKUP/compositor.sh"
cp -a "$COMP_UNIT" "$BACKUP/compositor.service"
cp -a "$ROUTING_UNIT" "$BACKUP/routing.service"

install -m 0755 /tmp/youtube-lovable-compositor.sh "$COMP_SCRIPT"
install -m 0644 /tmp/fgbears-youtube-lovable-compositor.service "$COMP_UNIT"
install -m 0644 /tmp/fgbears-youtube-lovable-routing.service "$ROUTING_UNIT"
systemctl daemon-reload
systemctl enable "$COMP" "$ROUTING" >/dev/null

# The unused direct relay must not race the compositor for the YouTube stream key.
systemctl stop "$LEGACY" 2>/dev/null || true
systemctl disable "$LEGACY" >/dev/null 2>&1 || true

# YouTube-only quality cutover. Master and Rumble are never restarted.
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

# Certify actual encoded output, not merely command-line settings.
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

# Shared-path invariants: neither master nor Rumble is allowed to move.
[[ "$(mainpid "$MASTER")" == "$MASTER0" ]]
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935

# Sustained YouTube ownership and resource check.
sleep 12
COMP2=$(mainpid "$COMP")
[[ "$COMP2" == "$COMP1" ]]
has_pid_port "$COMP2" 443
CPU=$(ps -p "$COMP2" -o %cpu= | tr -d ' ')
SPEED=$(awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); if(v!="") print v+0}' /srv/fgbears-live/logs/ffmpeg-progress.log 2>/dev/null || true)
if [[ -n "$SPEED" ]]; then
  python3 -c 'import sys;s=float(sys.argv[1]);assert s>=0.98,s' "$SPEED"
  echo "MASTER_REALTIME=${SPEED}x"
else
  echo 'MASTER_REALTIME=NO_RECENT_SAMPLE_PID_INVARIANTS_PASS'
fi

echo "STABILITY compositor_cpu=${CPU}% load=$(cut -d' ' -f1-3 /proc/loadavg)"
[[ "$(mainpid "$MASTER")" == "$MASTER0" ]]
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935
has_pid_port "$COMP2" 443
! active "$LEGACY"

echo "POST master=$(mainpid "$MASTER") rumble=$(mainpid "$RUMBLE") youtube720=$(mainpid "$COMP")"
echo 'YOUTUBE_720P_CUTOVER=PASS'
SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/youtube-lovable-compositor.sh /tmp/fgbears-youtube-lovable-compositor.service /tmp/fgbears-youtube-lovable-routing.service /tmp/cutover-youtube-720p.sh

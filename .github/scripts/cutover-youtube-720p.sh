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
  systemctl reset-failed "$LEGACY" || true
  systemctl start "$LEGACY" || true
  for _ in $(seq 1 20); do
    p=$(mainpid "$LEGACY")
    has_pid_port "$p" 443 && break
    sleep 1
  done
  systemctl start "$ROUTING" || true
  systemctl start "$COMP" || true
  echo "ROLLBACK_720P legacy=$(mainpid "$LEGACY") master=$(mainpid "$MASTER") rumble=$(mainpid "$RUMBLE")"
  rm -rf "$BACKUP"
  exit "$rc"
}
trap rollback EXIT

for u in "$MASTER" "$RUMBLE" "$LEGACY" "$COMP" "$ROUTING"; do active "$u"; done
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
LEGACY0=$(mainpid "$LEGACY")
COMP0=$(mainpid "$COMP")
has_pid_port "$LEGACY0" 443
has_pid_port "$RUMBLE0" 1935
echo "PRE master=$MASTER0 rumble=$RUMBLE0 legacy=$LEGACY0 compositor=$COMP0 load=$(cut -d' ' -f1-3 /proc/loadavg)"

cp -a "$COMP_SCRIPT" "$BACKUP/compositor.sh"
cp -a "$COMP_UNIT" "$BACKUP/compositor.service"
cp -a "$ROUTING_UNIT" "$BACKUP/routing.service"

install -m 0755 /tmp/youtube-lovable-compositor.sh "$COMP_SCRIPT"
install -m 0644 /tmp/fgbears-youtube-lovable-compositor.service "$COMP_UNIT"
install -m 0644 /tmp/fgbears-youtube-lovable-routing.service "$ROUTING_UNIT"
systemctl daemon-reload
systemctl enable "$COMP" "$ROUTING" >/dev/null

# Prepare the full-size Lovable mask while the legacy relay continues feeding YouTube.
systemctl stop "$COMP"
systemctl restart "$ROUTING"
MASK_OK=0
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

# Single-owner handoff: retire the legacy sender, then let the prepared compositor claim YouTube.
systemctl stop "$LEGACY"
systemctl disable "$LEGACY" >/dev/null 2>&1 || true
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

# Wait for bounded monitor output, then certify the actual compositor A/V contract.
SEG=''
for _ in $(seq 1 20); do
  SEG=$(find /run/fgbears-youtube-lovable-compositor -maxdepth 1 -type f -name 'monitor-*.ts' -size +1000c -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1{sub(/^[^ ]+ /,"");print}' || true)
  [[ -n "$SEG" ]] && break
  sleep 1
done
[[ -n "$SEG" ]]
V=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$SEG")
A=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate,channels -of csv=p=0 "$SEG")
python3 -c 'import sys; w,h,f=sys.argv[1].split(","); assert (w,h)==("1280","720"),(w,h); assert f in ("30/1","60/2"),f; sr,ch=sys.argv[2].split(","); assert sr=="44100",sr; assert ch=="2",ch' "$V" "$A"
echo "YOUTUBE_AV=PASS video=$V audio=$A"

# Shared paths are invariants: neither master nor Rumble may restart.
[[ "$(mainpid "$MASTER")" == "$MASTER0" ]]
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
has_pid_port "$RUMBLE0" 1935

# Confirm the 720p branch stays connected and the master still runs in real time.
sleep 12
COMP2=$(mainpid "$COMP")
[[ "$COMP2" == "$COMP1" ]]
has_pid_port "$COMP2" 443
SPEED=$(awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); print v+0}' /srv/fgbears-live/logs/ffmpeg-progress.log)
python3 -c 'import sys;s=float(sys.argv[1]);assert s>=0.98,s' "$SPEED"
CPU=$(ps -p "$COMP2" -o %cpu= | tr -d ' ')
echo "STABILITY master_speed=${SPEED}x compositor_cpu=${CPU}% load=$(cut -d' ' -f1-3 /proc/loadavg)"

# There must be one FGB YouTube sender socket, owned by the compositor.
FGB_443=$(ss -ntpH state established 2>/dev/null | awk '/:443 / && /ffmpeg/ {print}' | grep -c "pid=$COMP2" || true)
[[ "$FGB_443" -ge 1 ]]
! pgrep -x -f '/usr/local/bin/fgbears-youtube-relay|ffmpeg .*rtmps://a.rtmps.youtube.com/live2' >/dev/null 2>&1 || {
  # pgrep may also see the compositor command; explicitly reject only the old service PID/state.
  ! active "$LEGACY"
}

echo "POST master=$(mainpid "$MASTER") rumble=$(mainpid "$RUMBLE") youtube=$(mainpid "$COMP")"
echo 'YOUTUBE_720P_CUTOVER=PASS'
SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/youtube-lovable-compositor.sh /tmp/fgbears-youtube-lovable-compositor.service /tmp/fgbears-youtube-lovable-routing.service /tmp/cutover-youtube-720p.sh

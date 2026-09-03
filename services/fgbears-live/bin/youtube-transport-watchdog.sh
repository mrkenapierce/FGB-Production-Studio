#!/usr/bin/env bash
set -Eeuo pipefail

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
ROUTING=fgbears-youtube-lovable-routing.service
COMP=fgbears-youtube-lovable-compositor.service
LEGACY=fgbears-youtube-relay.service
MONDIR=/run/fgbears-youtube-lovable-compositor
STATE_DIR=/run/fgbears-youtube-transport-watchdog
PID_FILE=$STATE_DIR/last-compositor-pid

mkdir -p "$STATE_DIR"

pid(){ systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
active(){ systemctl is-active --quiet "$1"; }
conn(){
  local p=$1 port=$2
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v x=":$port" 'index($0,q)&&index($0,x){ok=1} END{exit(ok?0:1)}'
}
latest_seg(){
  find "$MONDIR" -maxdepth 1 -type f -name 'monitor-*.ts' -printf '%T@ %s %p\n' 2>/dev/null | sort -nr | head -n1
}
monitor_advancing(){
  local a b
  a=$(latest_seg || true)
  sleep 5
  b=$(latest_seg || true)
  [[ -n "$a" && -n "$b" && "$a" != "$b" ]]
}

# Never use this watchdog to disturb the shared production source or Rumble.
if ! active "$MASTER"; then
  echo "YOUTUBE_WATCHDOG=SKIP master_inactive"
  exit 0
fi
if ! active "$RUMBLE"; then
  echo "YOUTUBE_WATCHDOG=SKIP rumble_inactive"
  exit 0
fi
RP=$(pid "$RUMBLE")
if ! conn "$RP" 1935; then
  echo "YOUTUBE_WATCHDOG=SKIP rumble_socket_missing"
  exit 0
fi

# Routing is YouTube-only and safe to repair independently.
if ! active "$ROUTING"; then
  systemctl restart "$ROUTING"
  sleep 1
fi

CP=$(pid "$COMP")
PREV=0
[[ -r "$PID_FILE" ]] && read -r PREV < "$PID_FILE" || true
NEEDS_REFRESH=0
REASON=healthy

if ! active "$COMP" || [[ ! "$CP" =~ ^[1-9][0-9]*$ ]]; then
  NEEDS_REFRESH=1
  REASON=compositor_inactive
elif ! conn "$CP" 443; then
  NEEDS_REFRESH=1
  REASON=youtube_socket_missing
elif [[ "$PREV" =~ ^[1-9][0-9]*$ && "$PREV" != "$CP" ]]; then
  # systemd restarted the compositor between watchdog runs. A second clean
  # YouTube-only refresh prevents the public player from remaining attached to
  # a stale ingest session after the process-level recovery.
  NEEDS_REFRESH=1
  REASON=compositor_pid_changed
elif ! monitor_advancing; then
  NEEDS_REFRESH=1
  REASON=monitor_not_advancing
fi

if (( NEEDS_REFRESH )); then
  echo "YOUTUBE_WATCHDOG=REFRESH reason=$REASON old_pid=$CP previous_pid=$PREV"
  systemctl restart "$COMP"
  for _ in $(seq 1 25); do
    CP=$(pid "$COMP")
    if active "$COMP" && conn "$CP" 443; then
      break
    fi
    sleep 1
  done
  active "$COMP"
  conn "$CP" 443
  monitor_advancing
  echo "$CP" > "$PID_FILE"
  echo "YOUTUBE_WATCHDOG=RECOVERED reason=$REASON compositor=$CP"
else
  echo "$CP" > "$PID_FILE"
  echo "YOUTUBE_WATCHDOG=PASS compositor=$CP"
fi

# The retired direct YouTube sender must remain off.
if active "$LEGACY"; then
  systemctl stop "$LEGACY"
  systemctl disable "$LEGACY" >/dev/null 2>&1 || true
  echo "YOUTUBE_WATCHDOG=LEGACY_DISABLED"
fi

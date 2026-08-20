#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
TARGET_X_ACCOUNT='@epic501c3'
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-x" >&2; exit 77; }
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }

write_updates() {
  local enabled=$1 base=${2:-} key=${3:-}
  X_RELAY_ENABLED_VALUE="$enabled" X_RTMP_BASE_VALUE="$base" X_STREAM_KEY_VALUE="$key" X_ACCOUNT_VALUE="$TARGET_X_ACCOUNT" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines()
updates={
 'X_ACCOUNT_HANDLE':os.environ['X_ACCOUNT_VALUE'],
 'X_STREAM_ENABLED':'0',
 'X_RELAY_ENABLED':os.environ['X_RELAY_ENABLED_VALUE'],
 'X_LOCAL_UDP_URL':'udp://127.0.0.1:1937?pkt_size=1316',
 'X_SCHEDULE_TIMEZONE':'America/Chicago',
 'X_SCHEDULE_START':'09:00',
 'X_SCHEDULE_STOP':'17:00',
}
if os.environ.get('X_RTMP_BASE_VALUE'): updates['X_RTMP_BASE']=os.environ['X_RTMP_BASE_VALUE']
if os.environ.get('X_STREAM_KEY_VALUE'): updates['X_STREAM_KEY']=os.environ['X_STREAM_KEY_VALUE']
out=[]; seen=set()
for line in lines:
 key=line.split('=',1)[0] if '=' in line and not line.lstrip().startswith('#') else None
 if key in updates:
  if key not in seen: out.append(f'{key}={updates[key]}'); seen.add(key)
 else: out.append(line)
for key,value in updates.items():
 if key not in seen: out.append(f'{key}={value}')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
  chown root:fgbears "$ENV_FILE"; chmod 640 "$ENV_FILE"
}

in_schedule_window() {
  local now_hm
  now_hm=$(TZ=America/Chicago date +%H%M); now_hm=$((10#$now_hm))
  (( now_hm >= 900 && now_hm < 1700 ))
}

if [[ ${1:-} == "--disable" ]]; then
  write_updates 0
  systemctl disable --now fgbears-x-start.timer fgbears-x-stop.timer >/dev/null 2>&1 || true
  systemctl stop fgbears-x-relay.service >/dev/null 2>&1 || true
  systemctl reset-failed fgbears-x-relay.service || true
  echo "X schedule disabled for $TARGET_X_ACCOUNT. YouTube and Facebook were not restarted."
  exit 0
fi

printf 'Configuring scheduled X destination for %s.\n' "$TARGET_X_ACCOUNT"
printf 'X Live Studio RTMP/RTMPS URL: '
IFS= read -r x_rtmp_base
[[ "$x_rtmp_base" == rtmp://* || "$x_rtmp_base" == rtmps://* ]] || { echo "Invalid X source URL." >&2; exit 64; }
printf 'X Live Studio stream key: '
IFS= read -rs x_stream_key
printf '\n'
[[ -n "$x_stream_key" ]] || { echo "The X stream key cannot be empty." >&2; exit 64; }
[[ "$x_rtmp_base$x_stream_key" != *"|"* ]] || { echo "Unsupported X credential character." >&2; exit 64; }

write_updates 1 "$x_rtmp_base" "$x_stream_key"
unset x_stream_key
systemctl daemon-reload
systemctl reset-failed fgbears-x-relay.service || true
systemctl enable --now fgbears-x-start.timer fgbears-x-stop.timer
if in_schedule_window; then
  systemctl restart fgbears-x-relay.service
else
  systemctl stop fgbears-x-relay.service >/dev/null 2>&1 || true
fi
echo "X scheduled daily from 9:00 AM to 5:00 PM America/Chicago for $TARGET_X_ACCOUNT."

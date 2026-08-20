#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
TARGET_ACCOUNT='@epic501c3'
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-instagram" >&2; exit 77; }
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }

write_updates() {
  local enabled=$1 url=${2:-} key=${3:-}
  INSTAGRAM_RELAY_ENABLED_VALUE="$enabled" INSTAGRAM_STREAM_URL_VALUE="$url" INSTAGRAM_STREAM_KEY_VALUE="$key" INSTAGRAM_ACCOUNT_VALUE="$TARGET_ACCOUNT" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines()
updates={
 'INSTAGRAM_ACCOUNT_HANDLE':os.environ['INSTAGRAM_ACCOUNT_VALUE'],
 'INSTAGRAM_RELAY_ENABLED':os.environ['INSTAGRAM_RELAY_ENABLED_VALUE'],
 'INSTAGRAM_LOCAL_UDP_URL':'udp://127.0.0.1:1938?pkt_size=1316',
 'INSTAGRAM_SCHEDULE_TIMEZONE':'America/Chicago',
 'INSTAGRAM_SCHEDULE_START':'09:00',
 'INSTAGRAM_SCHEDULE_STOP':'17:00',
}
if os.environ.get('INSTAGRAM_STREAM_URL_VALUE'): updates['INSTAGRAM_STREAM_URL']=os.environ['INSTAGRAM_STREAM_URL_VALUE']
if os.environ.get('INSTAGRAM_STREAM_KEY_VALUE'): updates['INSTAGRAM_STREAM_KEY']=os.environ['INSTAGRAM_STREAM_KEY_VALUE']
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

in_window() { local n; n=$(TZ=America/Chicago date +%H%M); n=$((10#$n)); (( n >= 900 && n < 1700 )); }

if [[ ${1:-} == "--disable" ]]; then
  write_updates 0
  systemctl disable --now fgbears-instagram-start.timer fgbears-instagram-stop.timer >/dev/null 2>&1 || true
  systemctl stop fgbears-instagram-relay.service >/dev/null 2>&1 || true
  echo "Instagram relay disabled. Other destinations were not restarted."
  exit 0
fi

printf 'Instagram Live stream URL: '; IFS= read -r stream_url
[[ "$stream_url" == rtmp://* || "$stream_url" == rtmps://* ]] || { echo "Invalid Instagram stream URL." >&2; exit 64; }
printf 'Instagram Live stream key: '; IFS= read -rs stream_key; printf '\n'
[[ -n "$stream_key" ]] || { echo "Instagram stream key cannot be empty." >&2; exit 64; }

write_updates 1 "$stream_url" "$stream_key"
unset stream_key
systemctl daemon-reload
systemctl reset-failed fgbears-instagram-relay.service || true
systemctl enable --now fgbears-instagram-start.timer fgbears-instagram-stop.timer
if in_window; then systemctl restart fgbears-instagram-relay.service; else systemctl stop fgbears-instagram-relay.service >/dev/null 2>&1 || true; fi
echo "Instagram relay scheduled daily from 9:00 AM to 5:00 PM America/Chicago for $TARGET_ACCOUNT."

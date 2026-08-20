#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-facebook" >&2; exit 77; }
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }

write_updates() {
  local enabled=$1
  local base=${2:-}
  local key=${3:-}
  FACEBOOK_RELAY_ENABLED_VALUE="$enabled" FACEBOOK_RTMP_BASE_VALUE="$base" FACEBOOK_STREAM_KEY_VALUE="$key" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updates = {
    "FACEBOOK_STREAM_ENABLED": "0",
    "FACEBOOK_RELAY_ENABLED": os.environ["FACEBOOK_RELAY_ENABLED_VALUE"],
    "FACEBOOK_LOCAL_RTMP_BASE": "rtmp://127.0.0.1:1936/live",
}
if os.environ.get("FACEBOOK_RTMP_BASE_VALUE"):
    updates["FACEBOOK_RTMP_BASE"] = os.environ["FACEBOOK_RTMP_BASE_VALUE"]
if os.environ.get("FACEBOOK_STREAM_KEY_VALUE"):
    updates["FACEBOOK_STREAM_KEY"] = os.environ["FACEBOOK_STREAM_KEY_VALUE"]
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        if key not in seen:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chown root:fgbears "$ENV_FILE"
  chmod 640 "$ENV_FILE"
}

if [[ ${1:-} == "--disable" ]]; then
  write_updates 0
  systemctl disable --now fgbears-facebook-relay.service >/dev/null 2>&1 || true
  systemctl restart fgbears-youtube-relay.service
  echo "Facebook sidecar disabled. Primary encoder, YouTube, and X were not restarted."
  exit 0
fi

printf 'Facebook Live Producer RTMP/RTMPS server URL: '
IFS= read -r facebook_rtmp_base
[[ "$facebook_rtmp_base" == rtmp://* || "$facebook_rtmp_base" == rtmps://* ]] || {
  echo "The Facebook server URL must begin with rtmp:// or rtmps://" >&2
  exit 64
}
printf 'Facebook persistent stream key: '
IFS= read -rs facebook_stream_key
printf '\n'
[[ -n "$facebook_stream_key" ]] || { echo "The Facebook stream key cannot be empty." >&2; exit 64; }
[[ "$facebook_rtmp_base$facebook_stream_key" != *"|"* ]] || { echo "Unsupported | character in Facebook credentials." >&2; exit 64; }

write_updates 1 "$facebook_rtmp_base" "$facebook_stream_key"
unset facebook_stream_key

systemctl daemon-reload
systemctl reset-failed fgbears-facebook-relay.service fgbears-youtube-relay.service || true
systemctl enable fgbears-facebook-relay.service
systemctl restart fgbears-facebook-relay.service
# Restart only the YouTube copy-remux relay so it begins feeding the local
# Facebook listener. The primary encoder and X process remain untouched.
systemctl restart fgbears-youtube-relay.service

for _ in $(seq 1 30); do
  if systemctl is-active --quiet fgbears-facebook-relay.service && systemctl is-active --quiet fgbears-youtube-relay.service; then
    echo "Facebook isolated sidecar enabled. Primary encoder and X were not restarted."
    exit 0
  fi
  sleep 1
done

systemctl status fgbears-facebook-relay.service --no-pager --lines=40 >&2 || true
systemctl status fgbears-youtube-relay.service --no-pager --lines=40 >&2 || true
exit 1

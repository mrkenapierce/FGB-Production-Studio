#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-facebook" >&2; exit 77; }
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }

if [[ ${1:-} == "--disable" ]]; then
  python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updates = {"FACEBOOK_STREAM_ENABLED": "0"}
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
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
  systemctl restart fgbears-live.service
  echo "Facebook simulcast disabled. YouTube remains primary and X is unchanged."
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

FACEBOOK_RTMP_BASE_VALUE="$facebook_rtmp_base" FACEBOOK_STREAM_KEY_VALUE="$facebook_stream_key" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updates = {
    "FACEBOOK_STREAM_ENABLED": "1",
    "FACEBOOK_RTMP_BASE": os.environ["FACEBOOK_RTMP_BASE_VALUE"],
    "FACEBOOK_STREAM_KEY": os.environ["FACEBOOK_STREAM_KEY_VALUE"],
}
lines = text.splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

unset facebook_stream_key FACEBOOK_STREAM_KEY_VALUE FACEBOOK_RTMP_BASE_VALUE
chown root:fgbears "$ENV_FILE"
chmod 640 "$ENV_FILE"
systemctl restart fgbears-live.service
sleep 2
systemctl is-active --quiet fgbears-live.service || {
  systemctl status fgbears-live.service --no-pager --lines=40 >&2 || true
  exit 1
}
echo "Facebook simulcast enabled. The FGB program is encoded once and distributed through the existing tee transport."

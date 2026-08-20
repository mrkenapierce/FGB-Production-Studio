#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash /opt/fgbears-live/bin/configure-x.sh" >&2; exit 77; }
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }

if [[ ${1:-} == "--disable" ]]; then
  python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updates = {"X_STREAM_ENABLED": "0"}
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
  echo "X simulcast disabled. YouTube remains the primary output."
  exit 0
fi

printf 'X Live Studio RTMP/RTMPS URL: '
IFS= read -r x_rtmp_base
[[ "$x_rtmp_base" == rtmp://* || "$x_rtmp_base" == rtmps://* ]] || {
  echo "The X source URL must begin with rtmp:// or rtmps://" >&2
  exit 64
}
printf 'X Live Studio stream key: '
IFS= read -rs x_stream_key
printf '\n'
[[ -n "$x_stream_key" ]] || { echo "The X stream key cannot be empty." >&2; exit 64; }
[[ "$x_rtmp_base$x_stream_key" != *"|"* ]] || { echo "Unsupported | character in X source credentials." >&2; exit 64; }

X_RTMP_BASE_VALUE="$x_rtmp_base" X_STREAM_KEY_VALUE="$x_stream_key" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
updates = {
    "X_STREAM_ENABLED": "1",
    "X_RTMP_BASE": os.environ["X_RTMP_BASE_VALUE"],
    "X_STREAM_KEY": os.environ["X_STREAM_KEY_VALUE"],
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

unset x_stream_key X_STREAM_KEY_VALUE
chown root:fgbears "$ENV_FILE"
chmod 640 "$ENV_FILE"
systemctl restart fgbears-live.service
sleep 2
systemctl is-active --quiet fgbears-live.service || {
  systemctl status fgbears-live.service --no-pager --lines=40 >&2 || true
  exit 1
}
echo "X simulcast enabled. The FGB program is now encoded once and distributed to YouTube and X."

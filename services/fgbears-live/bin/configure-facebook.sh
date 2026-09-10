#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-facebook" >&2; exit 77; }
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }
[[ -x /usr/local/bin/fgbears-facebook-relay ]] || { echo "Facebook relay is not installed." >&2; exit 66; }
[[ -x /usr/local/bin/fgbears-facebook-window-sync ]] || { echo "Facebook window sync is not installed." >&2; exit 66; }

IFS= read -r facebook_rtmp_base
IFS= read -r facebook_stream_key
[[ "$facebook_rtmp_base" =~ ^rtmps://live-api-s\.facebook\.com(:443)?/rtmp/?$ ]] || {
  echo "Facebook server URL must be the approved Facebook Live RTMPS endpoint." >&2
  exit 64
}
[[ -n "$facebook_stream_key" ]] || { echo "Facebook stream key cannot be empty." >&2; exit 64; }
[[ "$facebook_stream_key" != *$'\n'* && "$facebook_stream_key" != *$'\r'* && "$facebook_stream_key" != *"|"* ]] || {
  echo "Facebook stream key must be one line and cannot contain |." >&2
  exit 64
}

temporary=$(mktemp /etc/fgbears-live/stream.env.XXXXXX)
trap 'rm -f "$temporary"' EXIT
FACEBOOK_RTMP_BASE_VALUE="$facebook_rtmp_base" FACEBOOK_STREAM_KEY_VALUE="$facebook_stream_key" python3 - "$ENV_FILE" "$temporary" <<'PY'
from pathlib import Path
import os, sys
src, dst = map(Path, sys.argv[1:])
updates = {
    "FACEBOOK_RELAY_ENABLED": "1",
    "FACEBOOK_LOCAL_UDP_URL": "udp://127.0.0.1:1944?pkt_size=1316",
    "FACEBOOK_RTMP_BASE": os.environ["FACEBOOK_RTMP_BASE_VALUE"],
    "FACEBOOK_STREAM_KEY": os.environ["FACEBOOK_STREAM_KEY_VALUE"],
    "FACEBOOK_SCHEDULE_TIMEZONE": "America/Chicago",
    "FACEBOOK_LIVE_MINUTES": "10",
    "FACEBOOK_OFF_MINUTES": "10",
    "FACEBOOK_LIVE_WINDOWS": "00-09,20-29,40-49",
}
retired = {"FACEBOOK_ROLLOVER_TIMES", "FACEBOOK_FIRST_START"}
seen = set()
out = []
for line in src.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
    if key in retired:
        continue
    if key in updates:
        if key not in seen:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
dst.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
chown root:fgbears "$temporary"
chmod 0640 "$temporary"
mv -f "$temporary" "$ENV_FILE"
trap - EXIT
unset facebook_stream_key

systemctl daemon-reload
systemctl disable --now fgbears-facebook-rollover.timer >/dev/null 2>&1 || true
systemctl stop fgbears-facebook-rollover.service >/dev/null 2>&1 || true
systemctl reset-failed fgbears-facebook-relay.service fgbears-facebook-window-sync.service || true
systemctl disable fgbears-facebook-relay.service >/dev/null 2>&1 || true
systemctl enable --now fgbears-facebook-window-sync.timer

# Align immediately with the current Central 10-minute block rather than waiting
# for the next boundary. The timer then re-evaluates at :00/:10/:20/:30/:40/:50.
systemctl start fgbears-facebook-window-sync.service

echo "Facebook relay configured for alternating 10-minute live/off windows all day in America/Chicago: LIVE :00-:09, :20-:29, :40-:49; OFF :10-:19, :30-:39, :50-:59."

#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-facebook-live-api" >&2; exit 77; }
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
META_ENV_FILE=${META_ENV_FILE:-/etc/fgbears-live/meta-live.env}
[[ -f "$ENV_FILE" ]] || { echo "Missing stream configuration: $ENV_FILE" >&2; exit 66; }
[[ -x /usr/local/bin/fgbears-facebook-window-sync ]] || { echo "Facebook window sync is not installed." >&2; exit 66; }

set_api_flag() {
  local value=$1
  FACEBOOK_LIVE_API_ENABLED_VALUE="$value" python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, sys
p = Path(sys.argv[1])
updates = {
    "FACEBOOK_RELAY_ENABLED": "1",
    "FACEBOOK_LIVE_API_ENABLED": os.environ["FACEBOOK_LIVE_API_ENABLED_VALUE"],
    "FACEBOOK_DYNAMIC_TARGET_FILE": "/srv/fgbears-live/runtime/facebook-secure-stream-url",
    "FACEBOOK_LIVE_ID_FILE": "/srv/fgbears-live/runtime/facebook-live-id",
    "FACEBOOK_SCHEDULE_TIMEZONE": "America/Chicago",
    "FACEBOOK_LIVE_MINUTES": "10",
    "FACEBOOK_OFF_MINUTES": "10",
    "FACEBOOK_LIVE_WINDOWS": "05-14,25-34,45-54",
    "FACEBOOK_LIVE_TITLE": "Football's Greatest Bears Live",
    "FACEBOOK_LIVE_DESCRIPTION": "Football's Greatest Bears live stream. Bear Down and FGB.",
}
lines = p.read_text(encoding="utf-8").splitlines()
seen = set(); out = []
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
p.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  chown root:fgbears "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
}

if [[ ${1:-} == "--disable" ]]; then
  set_api_flag 0
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  rm -f "$META_ENV_FILE" /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
  systemctl start fgbears-facebook-window-sync.service
  echo "Meta Live API mode disabled; Facebook returned to persistent-stream-key window cycling."
  exit 0
fi

IFS= read -rs meta_user_access_token
printf '\n'
[[ -n "$meta_user_access_token" ]] || { echo "Meta user access token cannot be empty." >&2; exit 64; }
[[ "$meta_user_access_token" != *$'\n'* && "$meta_user_access_token" != *$'\r'* ]] || { echo "Meta access token must be one line." >&2; exit 64; }

# Verify the token resolves to an account identity before storing it. This does
# not create a LiveVideo and therefore has no public Facebook side effect.
META_USER_ACCESS_TOKEN="$meta_user_access_token" python3 - <<'PY'
import json, os, urllib.error, urllib.parse, urllib.request
url = "https://graph.facebook.com/v26.0/me?" + urllib.parse.urlencode({"fields": "id,name"})
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['META_USER_ACCESS_TOKEN']}", "User-Agent": "FGB-Production-Studio/1.0"})
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        detail = json.loads(body).get("error", {})
        print(f"Meta token validation failed ({detail.get('code', exc.code)}): {detail.get('message', 'unknown error')}")
    except Exception:
        print(f"Meta token validation failed with HTTP {exc.code}.")
    raise SystemExit(69)
if not data.get("id"):
    print("Meta token validation returned no account id.")
    raise SystemExit(69)
print("Meta user access token validated for the authenticated Facebook account.")
PY

install -d -o root -g root -m 0755 /etc/fgbears-live
install -d -o root -g fgbears -m 0750 /srv/fgbears-live/runtime

# Keep exact pre-activation state so a failed permission check or public-live
# creation can restore the persistent-key mode without disturbing other outputs.
stream_backup=$(mktemp /etc/fgbears-live/stream.env.backup.XXXXXX)
cp -a "$ENV_FILE" "$stream_backup"
meta_backup=""
if [[ -e "$META_ENV_FILE" ]]; then
  meta_backup=$(mktemp /etc/fgbears-live/meta-live.env.backup.XXXXXX)
  cp -a "$META_ENV_FILE" "$meta_backup"
fi
rollback() {
  local status=$?
  if (( status == 0 )); then
    rm -f "$stream_backup" ${meta_backup:+"$meta_backup"}
    return 0
  fi
  echo "Meta Live API activation failed; restoring prior Facebook configuration." >&2
  cp -a "$stream_backup" "$ENV_FILE"
  if [[ -n "$meta_backup" && -e "$meta_backup" ]]; then
    cp -a "$meta_backup" "$META_ENV_FILE"
  else
    rm -f "$META_ENV_FILE"
  fi
  rm -f "$stream_backup" ${meta_backup:+"$meta_backup"}
  rm -f /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  systemctl start fgbears-facebook-window-sync.service >/dev/null 2>&1 || true
  exit "$status"
}
trap rollback EXIT

temporary=$(mktemp /etc/fgbears-live/meta-live.env.XXXXXX)
printf 'META_USER_ACCESS_TOKEN=%s\n' "$meta_user_access_token" > "$temporary"
printf 'META_GRAPH_VERSION=v26.0\n' >> "$temporary"
chown root:root "$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$META_ENV_FILE"
unset meta_user_access_token

set_api_flag 1
rm -f /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
systemctl daemon-reload
systemctl reset-failed fgbears-facebook-relay.service fgbears-facebook-window-sync.service || true
systemctl enable --now fgbears-facebook-window-sync.timer

# Align immediately. If this is an active :05-anchored window, this creates the
# public LiveVideo now; otherwise the next :05/:25/:45 boundary will do so.
systemctl start fgbears-facebook-window-sync.service

trap - EXIT
rm -f "$stream_backup" ${meta_backup:+"$meta_backup"}
echo "Meta Live API mode enabled for public Facebook Live creation on :05/:25/:45 windows."

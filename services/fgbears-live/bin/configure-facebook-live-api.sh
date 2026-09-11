#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo fgbears-configure-facebook-live-api" >&2; exit 77; }
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
META_TOKEN_FILE=${META_TOKEN_FILE:-/etc/fgbears-live/meta-user-access-token}
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
    "META_GRAPH_VERSION": "v26.0",
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
  rm -f "$META_TOKEN_FILE" /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
  systemctl start fgbears-facebook-window-sync.service
  echo "Meta Live API mode disabled; Facebook returned to persistent-stream-key window cycling."
  exit 0
fi

IFS= read -rs meta_user_access_token
printf '\n'
[[ -n "$meta_user_access_token" ]] || { echo "Meta user access token cannot be empty." >&2; exit 64; }
[[ "$meta_user_access_token" != *$'\n'* && "$meta_user_access_token" != *$'\r'* ]] || { echo "Meta access token must be one line." >&2; exit 64; }

# Validate identity, publish_video, and the Live Video API itself without creating
# any visible Facebook post. The UNPUBLISHED probe is deleted before activation.
META_USER_ACCESS_TOKEN="$meta_user_access_token" python3 - <<'PY'
import json, os, urllib.error, urllib.parse, urllib.request
base = "https://graph.facebook.com/v26.0"
token = os.environ["META_USER_ACCESS_TOKEN"]
headers = {"Authorization": f"Bearer {token}", "User-Agent": "FGB-Production-Studio/1.0"}

def decode_error(exc):
    body = exc.read().decode("utf-8", errors="replace")
    try:
        detail = json.loads(body).get("error", {})
        return detail.get("code", exc.code), detail.get("message", "unknown error")
    except Exception:
        return exc.code, "unknown error"

def get(path, fields=None):
    q = {"fields": fields} if fields else {}
    url = base + path + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))

try:
    me = get("/me", "id,name")
    perms = get("/me/permissions")
except urllib.error.HTTPError as exc:
    code, msg = decode_error(exc)
    print(f"Meta token validation failed ({code}): {msg}")
    raise SystemExit(69)
if not me.get("id"):
    print("Meta token validation returned no account id.")
    raise SystemExit(69)
granted = {p.get("permission") for p in perms.get("data", []) if p.get("status") == "granted"}
if "publish_video" not in granted:
    print("Meta token is valid but publish_video is not granted.")
    raise SystemExit(69)

probe_payload = urllib.parse.urlencode({
    "status": "UNPUBLISHED",
    "title": "FGB Production Live API Probe",
    "stop_on_delete_stream": "true",
    "fields": "id,secure_stream_url",
}).encode("utf-8")
probe_req = urllib.request.Request(
    base + "/me/live_videos",
    data=probe_payload,
    method="POST",
    headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
)
try:
    with urllib.request.urlopen(probe_req, timeout=20) as response:
        probe = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    code, msg = decode_error(exc)
    print(f"Meta Live Video API probe failed ({code}): {msg}")
    raise SystemExit(69)
probe_id = probe.get("id")
secure_url = probe.get("secure_stream_url")
if not probe_id or not isinstance(secure_url, str) or not secure_url.startswith("rtmps://"):
    print("Meta Live Video API probe returned no LiveVideo id or secure ingest URL.")
    raise SystemExit(69)

# Remove the invisible probe immediately. Refuse activation if cleanup fails.
delete_req = urllib.request.Request(
    base + "/" + urllib.parse.quote(str(probe_id), safe=""),
    data=b"",
    method="DELETE",
    headers=headers,
)
try:
    with urllib.request.urlopen(delete_req, timeout=20) as response:
        deleted = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    code, msg = decode_error(exc)
    print(f"Meta Live Video API probe cleanup failed ({code}): {msg}")
    raise SystemExit(69)
if deleted is not True and not (isinstance(deleted, dict) and deleted.get("success") is True):
    print("Meta Live Video API probe cleanup did not confirm deletion.")
    raise SystemExit(69)
print("Meta user token, publish_video permission, and Live Video API probe validated.")
PY

install -d -o root -g root -m 0755 /etc/fgbears-live
install -d -o root -g fgbears -m 0750 /srv/fgbears-live/runtime

# Keep exact pre-activation state so any failure restores persistent-key mode.
stream_backup=$(mktemp /etc/fgbears-live/stream.env.backup.XXXXXX)
cp -a "$ENV_FILE" "$stream_backup"
token_backup=""
if [[ -e "$META_TOKEN_FILE" ]]; then
  token_backup=$(mktemp /etc/fgbears-live/meta-token.backup.XXXXXX)
  cp -a "$META_TOKEN_FILE" "$token_backup"
fi
rollback() {
  local status=$?
  if (( status == 0 )); then
    rm -f "$stream_backup" ${token_backup:+"$token_backup"}
    return 0
  fi
  echo "Meta Live API activation failed; restoring prior Facebook configuration." >&2
  cp -a "$stream_backup" "$ENV_FILE"
  if [[ -n "$token_backup" && -e "$token_backup" ]]; then
    cp -a "$token_backup" "$META_TOKEN_FILE"
  else
    rm -f "$META_TOKEN_FILE"
  fi
  rm -f "$stream_backup" ${token_backup:+"$token_backup"}
  rm -f /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  systemctl start fgbears-facebook-window-sync.service >/dev/null 2>&1 || true
  exit "$status"
}
trap rollback EXIT

temporary=$(mktemp /etc/fgbears-live/meta-user-access-token.XXXXXX)
printf '%s\n' "$meta_user_access_token" > "$temporary"
chown root:root "$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$META_TOKEN_FILE"
unset meta_user_access_token

set_api_flag 1
rm -f /srv/fgbears-live/runtime/facebook-secure-stream-url /srv/fgbears-live/runtime/facebook-live-id
systemctl daemon-reload
systemctl reset-failed fgbears-facebook-relay.service fgbears-facebook-window-sync.service || true
systemctl enable --now fgbears-facebook-window-sync.timer

# Align immediately. In an active window this creates the public LiveVideo now;
# otherwise the next :05/:25/:45 boundary performs the first creation.
systemctl start fgbears-facebook-window-sync.service

trap - EXIT
rm -f "$stream_backup" ${token_backup:+"$token_backup"}
echo "Meta Live API mode enabled for public Facebook Live creation on :05/:25/:45 windows."

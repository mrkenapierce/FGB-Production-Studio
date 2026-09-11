#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
META_TOKEN_FILE=${META_TOKEN_FILE:-/etc/fgbears-live/meta-user-access-token}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${FACEBOOK_LIVE_API_ENABLED:=0}"
: "${META_GRAPH_VERSION:=v26.0}"
: "${FACEBOOK_DYNAMIC_TARGET_FILE:=/srv/fgbears-live/runtime/facebook-secure-stream-url}"
: "${FACEBOOK_LIVE_ID_FILE:=/srv/fgbears-live/runtime/facebook-live-id}"
: "${FACEBOOK_LIVE_TITLE:=Football's Greatest Bears Live}"
: "${FACEBOOK_LIVE_DESCRIPTION:=Football's Greatest Bears live stream. Bear Down and FGB.}"

truthy() {
  case "${1,,}" in 1|true|yes|on) return 0 ;; *) return 1 ;; esac
}

fallback_to_persistent_key() {
  echo "Meta Live API creation failed; restoring the known-working persistent-key Facebook mode." >&2
  python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = p.read_text(encoding="utf-8").splitlines()
out = []
seen = False
for line in lines:
    if line.startswith("FACEBOOK_LIVE_API_ENABLED="):
        if not seen:
            out.append("FACEBOOK_LIVE_API_ENABLED=0")
            seen = True
    else:
        out.append(line)
if not seen:
    out.append("FACEBOOK_LIVE_API_ENABLED=0")
tmp = p.with_suffix(p.suffix + ".tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
tmp.replace(p)
PY
  chown root:fgbears "$ENV_FILE"
  chmod 0640 "$ENV_FILE"
  rm -f "$FACEBOOK_DYNAMIC_TARGET_FILE" "$FACEBOOK_LIVE_ID_FILE"
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  systemctl reset-failed fgbears-facebook-relay.service || true
  systemctl start fgbears-facebook-relay.service
}

case "${FACEBOOK_RELAY_ENABLED:-0}" in
  1|true|TRUE|yes|YES|on|ON) ;;
  *)
    systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
    rm -f "$FACEBOOK_DYNAMIC_TARGET_FILE" "$FACEBOOK_LIVE_ID_FILE"
    exit 0
    ;;
esac

# Alternate 10-minute blocks continuously in America/Chicago, anchored on :05:
# LIVE : :05-:14, :25-:34, :45-:54
# OFF  : :15-:24, :35-:44, :55-:04
minute=$(TZ=America/Chicago date +%M)
minute=$((10#$minute))
shifted=$(((minute + 55) % 60))
slot=$((shifted / 10))

if (( slot % 2 != 0 )); then
  # stop_on_delete_stream=true makes the encoder disconnect end the LiveVideo.
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  rm -f "$FACEBOOK_DYNAMIC_TARGET_FILE" "$FACEBOOK_LIVE_ID_FILE"
  exit 0
fi

# If this live window is already active, do not create a duplicate Facebook post.
if systemctl is-active --quiet fgbears-facebook-relay.service; then
  exit 0
fi

if ! truthy "$FACEBOOK_LIVE_API_ENABLED"; then
  systemctl reset-failed fgbears-facebook-relay.service || true
  systemctl start fgbears-facebook-relay.service
  exit 0
fi

[[ $EUID -eq 0 ]] || { echo "Meta Live API window sync must run as root." >&2; exit 77; }
[[ -r "$META_TOKEN_FILE" ]] || { fallback_to_persistent_key; exit 0; }
IFS= read -r META_USER_ACCESS_TOKEN < "$META_TOKEN_FILE"
[[ -n "$META_USER_ACCESS_TOKEN" ]] || { fallback_to_persistent_key; exit 0; }

install -d -o root -g fgbears -m 0750 "$(dirname "$FACEBOOK_DYNAMIC_TARGET_FILE")"
rm -f "$FACEBOOK_DYNAMIC_TARGET_FILE" "$FACEBOOK_LIVE_ID_FILE"

tmp_json=$(mktemp)
trap 'rm -f "$tmp_json"' EXIT
if ! META_USER_ACCESS_TOKEN="$META_USER_ACCESS_TOKEN" \
META_GRAPH_VERSION="$META_GRAPH_VERSION" \
FACEBOOK_LIVE_TITLE="$FACEBOOK_LIVE_TITLE" \
FACEBOOK_LIVE_DESCRIPTION="$FACEBOOK_LIVE_DESCRIPTION" \
python3 - "$tmp_json" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

out = sys.argv[1]
token = os.environ["META_USER_ACCESS_TOKEN"]
version = os.environ.get("META_GRAPH_VERSION", "v26.0")
base = f"https://graph.facebook.com/{version}"
endpoint = f"{base}/me/live_videos"
payload = urllib.parse.urlencode({
    "status": "LIVE_NOW",
    "title": os.environ["FACEBOOK_LIVE_TITLE"],
    "description": os.environ["FACEBOOK_LIVE_DESCRIPTION"],
    "privacy": json.dumps({"value": "EVERYONE"}),
    "stop_on_delete_stream": "true",
    "fields": "id,secure_stream_url",
}).encode("utf-8")
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "FGB-Production-Studio/1.0",
}
req = urllib.request.Request(endpoint, data=payload, method="POST", headers=headers)
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        detail = json.loads(body).get("error", {})
        message = detail.get("message", "Meta Live API request failed")
        code = detail.get("code", exc.code)
        print(f"Meta Live API error {code}: {message}", file=sys.stderr)
    except Exception:
        print(f"Meta Live API HTTP error {exc.code}", file=sys.stderr)
    raise SystemExit(69)
except Exception as exc:
    print(f"Meta Live API transport error: {exc}", file=sys.stderr)
    raise SystemExit(69)

live_id = data.get("id")
secure_url = data.get("secure_stream_url")
if live_id and not secure_url:
    lookup = f"{base}/{urllib.parse.quote(str(live_id), safe='')}?" + urllib.parse.urlencode({"fields": "id,secure_stream_url"})
    req = urllib.request.Request(lookup, headers={"Authorization": f"Bearer {token}", "User-Agent": "FGB-Production-Studio/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            detail = json.loads(response.read().decode("utf-8"))
        secure_url = detail.get("secure_stream_url")
    except Exception:
        secure_url = None

if not isinstance(secure_url, str) or not secure_url.startswith("rtmps://") or not live_id:
    print("Meta Live API did not return a secure_stream_url and LiveVideo id.", file=sys.stderr)
    raise SystemExit(69)
with open(out, "w", encoding="utf-8") as fh:
    json.dump({"secure_stream_url": secure_url, "id": str(live_id)}, fh)
PY
then
  trap - EXIT
  rm -f "$tmp_json"
  unset META_USER_ACCESS_TOKEN
  fallback_to_persistent_key
  exit 0
fi
unset META_USER_ACCESS_TOKEN

secure_url=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["secure_stream_url"])' "$tmp_json")
live_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$tmp_json")
[[ "$secure_url" == rtmps://* ]] || { fallback_to_persistent_key; exit 0; }
[[ "$secure_url" != *$'\n'* && "$secure_url" != *$'\r'* && "$secure_url" != *"|"* ]] || { fallback_to_persistent_key; exit 0; }

printf '%s\n' "$secure_url" > "$FACEBOOK_DYNAMIC_TARGET_FILE"
printf '%s\n' "$live_id" > "$FACEBOOK_LIVE_ID_FILE"
chown root:fgbears "$FACEBOOK_DYNAMIC_TARGET_FILE" "$FACEBOOK_LIVE_ID_FILE"
chmod 0640 "$FACEBOOK_DYNAMIC_TARGET_FILE"
chmod 0644 "$FACEBOOK_LIVE_ID_FILE"

systemctl reset-failed fgbears-facebook-relay.service || true
if ! systemctl start fgbears-facebook-relay.service; then
  fallback_to_persistent_key
  exit 0
fi

echo "Created Facebook LiveVideo ${live_id} and started the isolated relay for the current :05-anchored live window."

#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

export DEBIAN_FRONTEND=noninteractive
required_packages=(
  ffmpeg ca-certificates curl git jq rsync python3 python3-pil qrencode fonts-dejavu-core
)
missing_packages=()
for package in "${required_packages[@]}"; do
  if ! dpkg-query -W -f='${Status}\n' "$package" 2>/dev/null | grep -Fqx 'install ok installed'; then
    missing_packages+=("$package")
  fi
done

if ((${#missing_packages[@]})); then
  echo "Installing missing packages: ${missing_packages[*]}"
  apt-get \
    -o Acquire::Retries=3 \
    -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 \
    update
  apt-get \
    -o Acquire::Retries=3 \
    -o Acquire::http::Timeout=30 \
    -o Acquire::https::Timeout=30 \
    install -y --no-install-recommends "${missing_packages[@]}"
else
  echo "All required FGBears Live packages are already installed; skipping apt."
fi

if ! id fgbears >/dev/null 2>&1; then
  useradd --system --home-dir /srv/fgbears-live --shell /usr/sbin/nologin fgbears
fi

install -d -m 0755 /opt/fgbears-live
rsync -a --delete "$SOURCE_DIR/" /opt/fgbears-live/

mv /opt/fgbears-live/bin/ad-overlay.py /opt/fgbears-live/bin/ad-overlay-base.py
install -m 0755 /opt/fgbears-live/bin/ad-overlay-smart.py /opt/fgbears-live/bin/ad-overlay.py

install -d -m 0755 /opt/fgbears-live/assets
base64 --decode "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" > /opt/fgbears-live/assets/epic-logo.png
chmod 0644 /opt/fgbears-live/assets/epic-logo.png

install -m 0644 \
  "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" \
  /opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg
python3 -c 'from PIL import Image; p="/opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg"; im=Image.open(p); im.load(); assert im.format == "JPEG"; assert im.size == (798, 470)'

install -d -o fgbears -g fgbears -m 0755 /srv/fgbears-live /srv/fgbears-live/media /srv/fgbears-live/incoming /srv/fgbears-live/logs /srv/fgbears-live/runtime
install -d -o root -g root -m 0755 /srv/fgbears-live/health
install -d -o root -g fgbears -m 0750 /etc/fgbears-live

install -m 0755 /opt/fgbears-live/bin/start-stream.sh /usr/local/bin/fgbears-start-stream
install -m 0755 /opt/fgbears-live/bin/youtube-relay.sh /usr/local/bin/fgbears-youtube-relay
install -m 0755 /opt/fgbears-live/bin/facebook-relay.sh /usr/local/bin/fgbears-facebook-relay
install -m 0755 /opt/fgbears-live/bin/configure-x.sh /usr/local/bin/fgbears-configure-x
install -m 0755 /opt/fgbears-live/bin/configure-facebook.sh /usr/local/bin/fgbears-configure-facebook
install -m 0755 /opt/fgbears-live/bin/normalize-library.sh /usr/local/bin/fgbears-normalize
install -m 0755 /opt/fgbears-live/bin/validate-media.sh /usr/local/bin/fgbears-validate
install -m 0755 /opt/fgbears-live/bin/rebuild-playlist.sh /usr/local/bin/fgbears-rebuild-playlist
install -m 0755 /opt/fgbears-live/bin/add-episode.sh /usr/local/bin/fgbears-add-episode
install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck
install -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status

install -m 0644 /opt/fgbears-live/systemd/fgbears-live.service /etc/systemd/system/fgbears-live.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-youtube-relay.service /etc/systemd/system/fgbears-youtube-relay.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-facebook-relay.service /etc/systemd/system/fgbears-facebook-relay.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-facebook-start.service /etc/systemd/system/fgbears-facebook-start.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-facebook-stop.service /etc/systemd/system/fgbears-facebook-stop.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-facebook-start.timer /etc/systemd/system/fgbears-facebook-start.timer
install -m 0644 /opt/fgbears-live/systemd/fgbears-facebook-stop.timer /etc/systemd/system/fgbears-facebook-stop.timer
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.service /etc/systemd/system/fgbears-live-health.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.timer /etc/systemd/system/fgbears-live-health.timer

ENV_PATH=/etc/fgbears-live/stream.env
if [[ ! -e "$ENV_PATH" ]]; then
  install -o root -g fgbears -m 0640 /opt/fgbears-live/config/stream.env.example "$ENV_PATH"
fi

# Preserve credentials, lock out direct Meta output, and keep the Facebook
# schedule independent of the primary encoder and dedicated YouTube relay.
python3 - "$ENV_PATH" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key] = value

local_base = values.get("YOUTUBE_LOCAL_RTMP_BASE") or "rtmp://127.0.0.1:1935/live"
current_base = values.get("YOUTUBE_RTMP_BASE", "")
upstream = values.get("YOUTUBE_UPSTREAM_RTMP_BASE", "")
if not upstream:
    if current_base and not current_base.startswith("rtmp://127.0.0.1:"):
        upstream = current_base
    else:
        upstream = "rtmps://a.rtmps.youtube.com/live2"

def truthy(value):
    return value.strip().lower() in {"1", "true", "yes", "on"}

relay_enabled = values.get("FACEBOOK_RELAY_ENABLED")
if relay_enabled is None:
    relay_enabled = "1" if truthy(values.get("FACEBOOK_STREAM_ENABLED", "0")) else "0"

updates = {
    "YOUTUBE_RTMP_BASE": local_base,
    "YOUTUBE_LOCAL_RTMP_BASE": local_base,
    "YOUTUBE_UPSTREAM_RTMP_BASE": upstream,
    "FACEBOOK_STREAM_ENABLED": "0",
    "FACEBOOK_RELAY_ENABLED": relay_enabled,
    "FACEBOOK_LOCAL_UDP_URL": "udp://127.0.0.1:1936?pkt_size=1316",
    "FACEBOOK_SCHEDULE_TIMEZONE": "America/Chicago",
    "FACEBOOK_SCHEDULE_START": "12:00",
    "FACEBOOK_SCHEDULE_STOP": "15:25",
}
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key in updates:
            if key not in seen:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
chown root:fgbears "$ENV_PATH"
chmod 0640 "$ENV_PATH"

systemctl daemon-reload
systemctl enable fgbears-youtube-relay.service
systemctl disable fgbears-facebook-relay.service >/dev/null 2>&1 || true

facebook_configured=false
if grep -Eq '^FACEBOOK_RELAY_ENABLED=(1|true|yes|on)$' "$ENV_PATH" && \
   grep -Eq '^FACEBOOK_RTMP_BASE=rtmps?://.+' "$ENV_PATH" && \
   awk -F= '/^FACEBOOK_STREAM_KEY=/{if(length(substr($0,index($0,"=")+1))>0) ok=1} END{exit ok?0:1}' "$ENV_PATH"; then
  facebook_configured=true
fi

if [[ "$facebook_configured" == true ]]; then
  systemctl enable --now fgbears-facebook-start.timer fgbears-facebook-stop.timer
  now_hm=$(TZ=America/Chicago date +%H%M)
  now_hm=$((10#$now_hm))
  systemctl reset-failed fgbears-facebook-relay.service || true
  if (( now_hm >= 1200 && now_hm < 1525 )); then
    systemctl restart fgbears-facebook-relay.service
  else
    systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
  fi
else
  systemctl disable --now fgbears-facebook-start.timer fgbears-facebook-stop.timer >/dev/null 2>&1 || true
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
fi

# The YouTube relay remains a dedicated single-output copy-remux service.
systemctl reset-failed fgbears-youtube-relay.service || true
systemctl restart fgbears-youtube-relay.service
systemctl enable --now fgbears-live-health.timer

echo "Installed FGBears Live with one primary encode, dedicated YouTube relay, X output, and a scheduled isolated Facebook sidecar (12:00-15:25 America/Chicago)."

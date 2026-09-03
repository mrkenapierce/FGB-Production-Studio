#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

export DEBIAN_FRONTEND=noninteractive
required_packages=(
  ffmpeg ca-certificates curl git jq rsync python3 python3-pil python3-qrcode qrencode fonts-dejavu-core
)
missing_packages=()
for package in "${required_packages[@]}"; do
  if ! dpkg-query -W -f='${Status}\n' "$package" 2>/dev/null | grep -Fqx 'install ok installed'; then
    missing_packages+=("$package")
  fi
done

if ((${#missing_packages[@]})); then
  echo "Installing missing packages: ${missing_packages[*]}"
  apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
  apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends "${missing_packages[@]}"
else
  echo "All required FGBears Live packages are already installed; skipping apt."
fi

if ! id fgbears >/dev/null 2>&1; then
  useradd --system --home-dir /srv/fgbears-live --shell /usr/sbin/nologin fgbears
fi

install -d -m 0755 /opt/fgbears-live
rsync -a --delete "$SOURCE_DIR/" /opt/fgbears-live/

# Historical YouTube implementations are retained only as inert source. They
# may be inspected for provenance but can never be executed from quarantine.
if [[ -d /opt/fgbears-live/quarantine ]]; then
  find /opt/fgbears-live/quarantine -type d -exec chmod 0755 {} +
  find /opt/fgbears-live/quarantine -type f -exec chmod 0644 {} +
fi

mv /opt/fgbears-live/bin/ad-overlay.py /opt/fgbears-live/bin/ad-overlay-base.py
install -m 0755 /opt/fgbears-live/bin/ad-overlay-smart.py /opt/fgbears-live/bin/ad-overlay.py

install -d -m 0755 /opt/fgbears-live/assets
base64 --decode "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" > /opt/fgbears-live/assets/epic-logo.png
chmod 0644 /opt/fgbears-live/assets/epic-logo.png
install -m 0644 "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" /opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg
python3 -c 'from PIL import Image; p="/opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg"; im=Image.open(p); im.load(); assert im.format == "JPEG"; assert im.size == (798, 470)'

install -d -o fgbears -g fgbears -m 0755 /srv/fgbears-live /srv/fgbears-live/media /srv/fgbears-live/incoming /srv/fgbears-live/logs /srv/fgbears-live/runtime
install -d -o root -g root -m 0755 /srv/fgbears-live/health
install -d -o root -g fgbears -m 0750 /etc/fgbears-live

# Shared/master and Rumble are the only common transport tools installed here.
install -m 0755 /opt/fgbears-live/bin/start-stream.sh /usr/local/bin/fgbears-start-stream
install -m 0755 /opt/fgbears-live/bin/rumble-relay.sh /usr/local/bin/fgbears-rumble-relay
install -m 0755 /opt/fgbears-live/bin/configure-rumble.sh /usr/local/bin/fgbears-configure-rumble
install -m 0755 /opt/fgbears-live/bin/normalize-library.sh /usr/local/bin/fgbears-normalize
install -m 0755 /opt/fgbears-live/bin/validate-media.sh /usr/local/bin/fgbears-validate
install -m 0755 /opt/fgbears-live/bin/rebuild-playlist.sh /usr/local/bin/fgbears-rebuild-playlist
install -m 0755 /opt/fgbears-live/bin/add-episode.sh /usr/local/bin/fgbears-add-episode
install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck
install -m 0755 /opt/fgbears-live/bin/audio-health.py /usr/local/bin/fgbears-audio-health
install -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status

install -m 0644 /opt/fgbears-live/systemd/fgbears-live.service /etc/systemd/system/fgbears-live.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-rumble-relay.service /etc/systemd/system/fgbears-rumble-relay.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.service /etc/systemd/system/fgbears-live-health.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.timer /etc/systemd/system/fgbears-live-health.timer

# YouTube has exactly one authorized destination-specific implementation.
install -d -m 0755 /opt/fgbears-live/youtube-v2 /opt/fgbears-live/youtube-v2/creatives
install -m 0755 "$SOURCE_DIR/youtube-v2/run-youtube-v2.sh" /opt/fgbears-live/youtube-v2/run-youtube-v2.sh
install -m 0755 "$SOURCE_DIR/youtube-v2/youtube-v2-overlay.py" /opt/fgbears-live/youtube-v2/youtube-v2-overlay.py
install -m 0755 "$SOURCE_DIR/youtube-v2/verify-youtube-v2.sh" /opt/fgbears-live/youtube-v2/verify-youtube-v2.sh
install -m 0644 "$SOURCE_DIR/youtube-v2/fgbears-youtube-v2.service" /etc/systemd/system/fgbears-youtube-v2.service
install -m 0644 "$SOURCE_DIR/tools/build-youtube-rumble-trivia-card.py" /opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py

ENV_PATH=/etc/fgbears-live/stream.env
if [[ ! -e "$ENV_PATH" ]]; then
  install -o root -g fgbears -m 0640 /opt/fgbears-live/config/stream.env.example "$ENV_PATH"
fi

# Preserve credentials while pinning one shared master and one post-split
# YouTube-v2 destination path. All earlier YouTube relay/router/watchdog env
# toggles are removed so a future shared install cannot revive them.
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

current_base = values.get("YOUTUBE_RTMP_BASE", "")
upstream = values.get("YOUTUBE_UPSTREAM_RTMP_BASE", "")
if not upstream:
    if current_base and not current_base.startswith("rtmp://127.0.0.1:"):
        upstream = current_base
    else:
        upstream = "rtmps://a.rtmps.youtube.com/live2"

updates = {
    "YOUTUBE_LOCAL_UDP_URL": "udp://127.0.0.1:1939?pkt_size=1316",
    "YOUTUBE_UPSTREAM_RTMP_BASE": upstream,
    "RUMBLE_TRIVIA_URL": "https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html",
    "RUMBLE_TRIVIA_DISPLAY_URL": "rumble.com/v7eqrsu",
    "RUMBLE_LOCAL_UDP_URL": "udp://127.0.0.1:1940?pkt_size=1316",
    "RUMBLE_UPSTREAM_RTMP_BASE": "rtmp://rtmp.rumble.com/live",
    "FGB_YOUTUBE_PACKET_ROUTER_ENABLE": "0",
    "OUTPUT_FPS": "30",
    "AD_OVERLAY_FPS": "15",
    "CRAWL_OVERLAY_FPS": "30",
    "CRAWL_OVERLAY_SCRIPT": "/opt/fgbears-live/bin/crawl-overlay-hq.py",
    "CRAWL_TEXT_RENDER_SCALE": "2",
    "BEARS_NEWS_OVERLAY_PORT": "8789",
    "BEARS_NEWS_OVERLAY_FPS": "15",
    "BEARS_NEWS_SCROLL_PPS": "76",
}
retired_prefixes = ("X_", "INSTAGRAM_", "FACEBOOK_", "YOUTUBE_TRIVIA_")
retired_exact = {
    "FGB_YOUTUBE_TRIVIA_CARD_H264",
    "PODCAST_AUDIO_FILTER",
    "YOUTUBE_AUDIO_BITRATE",
    "YOUTUBE_AUDIO_SAMPLE_RATE",
    "YOUTUBE_AUDIO_CHANNELS",
    "YOUTUBE_VIDEO_BITRATE",
    "YOUTUBE_VIDEO_MAXRATE",
    "YOUTUBE_VIDEO_BUFSIZE",
    "YOUTUBE_RTMP_BASE",
}
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key.startswith(retired_prefixes) or key in retired_exact:
            continue
        if key in updates:
            if key not in seen:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
if not any(line.startswith("RUMBLE_STREAM_KEY=") for line in out):
    out.append("RUMBLE_STREAM_KEY=REPLACE_WITH_RUMBLE_STREAM_KEY")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
chown root:fgbears "$ENV_PATH"
chmod 0640 "$ENV_PATH"

# Remove every callable legacy YouTube transport/presentation entry point.
rm -f \
  /usr/local/bin/fgbears-youtube-relay \
  /usr/local/bin/fgbears-youtube-audio-watchdog \
  /opt/fgbears-live/bin/youtube-relay.sh \
  /opt/fgbears-live/bin/youtube-relay-legacy.sh \
  /opt/fgbears-live/bin/youtube-stream-router.py \
  /opt/fgbears-live/bin/youtube-stream-router-v5.py \
  /opt/fgbears-live/bin/youtube-trivia-overlay.py \
  /opt/fgbears-live/bin/youtube-question-mask.py \
  /opt/fgbears-live/bin/youtube-offhost-compositor.sh \
  /opt/fgbears-live/bin/youtube-compositor-source-relay.sh \
  /opt/fgbears-live/bin/youtube-audio-watchdog.sh

retired_units=(
  fgbears-youtube-output.service
  fgbears-youtube-relay.service
  fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service
  fgbears-youtube-lovable-compositor.service
  fgbears-youtube-audio-watchdog.service
  fgbears-youtube-audio-watchdog.timer
)
for unit in "${retired_units[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$unit" "/lib/systemd/system/$unit" "/usr/lib/systemd/system/$unit"
done
systemctl daemon-reload
for unit in "${retired_units[@]}"; do
  systemctl mask "$unit" >/dev/null 2>&1 || true
done

# Install/enable canonical units without restarting any live transport. The
# deployment workflow owns the smallest necessary restart for the change type.
systemctl enable fgbears-live.service fgbears-rumble-relay.service fgbears-youtube-v2.service >/dev/null
systemctl enable --now fgbears-live-health.timer

echo "Installed FGBears shared program with Rumble canonical output and sole YouTube-v2 destination overlay. Live transport was not restarted by installer."

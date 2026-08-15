#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ffmpeg ca-certificates curl git jq rsync python3 python3-pil qrencode fonts-dejavu-core

if ! id fgbears >/dev/null 2>&1; then
  useradd --system --home-dir /srv/fgbears-live --shell /usr/sbin/nologin fgbears
fi

install -d -m 0755 /opt/fgbears-live
rsync -a --delete "$SOURCE_DIR/" /opt/fgbears-live/

# Keep the mature renderer implementation as the base module and install the
# aspect-safe entry point at the path start-stream already launches. This makes
# every photo use the same no-crop/no-stretch fitting rule without changing the
# live stream's video-clock architecture.
mv /opt/fgbears-live/bin/ad-overlay.py /opt/fgbears-live/bin/ad-overlay-base.py
install -m 0755 /opt/fgbears-live/bin/ad-overlay-smart.py /opt/fgbears-live/bin/ad-overlay.py

install -d -m 0755 /opt/fgbears-live/assets
base64 --decode "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" > /opt/fgbears-live/assets/epic-logo.png
chmod 0644 /opt/fgbears-live/assets/epic-logo.png

# Install the approved FGB/EPIC card shown between sponsor advertisements and
# fail the deployment unless Pillow can fully decode the broadcast-sized file.
install -m 0644 \
  "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" \
  /opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg
python3 -c 'from PIL import Image; p="/opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg"; im=Image.open(p); im.load(); assert im.format == "JPEG"; assert im.size == (798, 470)'

install -d -o fgbears -g fgbears -m 0755 /srv/fgbears-live /srv/fgbears-live/media /srv/fgbears-live/incoming /srv/fgbears-live/logs /srv/fgbears-live/runtime
install -d -o root -g root -m 0755 /srv/fgbears-live/health
install -d -o root -g fgbears -m 0750 /etc/fgbears-live

install -m 0755 /opt/fgbears-live/bin/start-stream.sh /usr/local/bin/fgbears-start-stream
install -m 0755 /opt/fgbears-live/bin/normalize-library.sh /usr/local/bin/fgbears-normalize
install -m 0755 /opt/fgbears-live/bin/validate-media.sh /usr/local/bin/fgbears-validate
install -m 0755 /opt/fgbears-live/bin/rebuild-playlist.sh /usr/local/bin/fgbears-rebuild-playlist
install -m 0755 /opt/fgbears-live/bin/add-episode.sh /usr/local/bin/fgbears-add-episode
install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck
install -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status

install -m 0644 /opt/fgbears-live/systemd/fgbears-live.service /etc/systemd/system/fgbears-live.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.service /etc/systemd/system/fgbears-live-health.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.timer /etc/systemd/system/fgbears-live-health.timer

if [[ ! -e /etc/fgbears-live/stream.env ]]; then
  install -o root -g fgbears -m 0640 /opt/fgbears-live/config/stream.env.example /etc/fgbears-live/stream.env
fi

systemctl daemon-reload
systemctl enable --now fgbears-live-health.timer

echo "Installed FGBears Live with dynamic advertising. The stream remains stopped until a real stream key and at least one normalized episode are present."

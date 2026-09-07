#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

export DEBIAN_FRONTEND=noninteractive
required_packages=(ffmpeg ca-certificates curl git jq rsync python3 python3-pil qrencode fonts-dejavu-core)
missing_packages=()
for package in "${required_packages[@]}"; do
  if ! dpkg-query -W -f='${Status}\n' "$package" 2>/dev/null | grep -Fqx 'install ok installed'; then missing_packages+=("$package"); fi
done
apt_get_with_retry() {
  local attempt max_attempts=6
  for attempt in $(seq 1 "$max_attempts"); do
    if apt-get -o DPkg::Lock::Timeout=20 -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 "$@"; then return 0; fi
    (( attempt < max_attempts )) || return 1
    sleep 10
  done
}
if ((${#missing_packages[@]})); then apt_get_with_retry update; apt_get_with_retry install -y --no-install-recommends "${missing_packages[@]}"; fi

if ! id fgbears >/dev/null 2>&1; then useradd --system --home-dir /srv/fgbears-live --shell /usr/sbin/nologin fgbears; fi

install -d -m 0755 /opt/fgbears-live
rsync -a --delete "$SOURCE_DIR/" /opt/fgbears-live/
if [[ -d /opt/fgbears-live/quarantine ]]; then
  find /opt/fgbears-live/quarantine -type d -exec chmod 0755 {} +
  find /opt/fgbears-live/quarantine -type f -exec chmod 0644 {} +
fi

if [[ -f /opt/fgbears-live/bin/ad-overlay.py ]]; then
  mv /opt/fgbears-live/bin/ad-overlay.py /opt/fgbears-live/bin/ad-overlay-base.py
  install -m 0755 /opt/fgbears-live/bin/ad-overlay-smart.py /opt/fgbears-live/bin/ad-overlay.py
fi

install -d -m 0755 /opt/fgbears-live/assets
if [[ -f "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" ]]; then
  base64 --decode "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" > /opt/fgbears-live/assets/epic-logo.png
  chmod 0644 /opt/fgbears-live/assets/epic-logo.png
fi
if [[ -f "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" ]]; then install -m 0644 "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" /opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg; fi

install -d -o fgbears -g fgbears -m 0755 /srv/fgbears-live /srv/fgbears-live/media /srv/fgbears-live/incoming /srv/fgbears-live/logs /srv/fgbears-live/runtime
install -d -o root -g root -m 0755 /srv/fgbears-live/health
install -d -o root -g fgbears -m 0750 /etc/fgbears-live

install -m 0755 /opt/fgbears-live/bin/start-stream.sh /usr/local/bin/fgbears-start-stream
install -m 0755 /opt/fgbears-live/bin/youtube-copy-relay.sh /usr/local/bin/fgbears-youtube-copy-relay
install -m 0755 /opt/fgbears-live/bin/validate-media.sh /usr/local/bin/fgbears-validate
install -m 0755 /opt/fgbears-live/bin/rebuild-playlist.sh /usr/local/bin/fgbears-rebuild-playlist
install -m 0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck
install -m 0755 /opt/fgbears-live/bin/audio-health.py /usr/local/bin/fgbears-audio-health
install -m 0755 /opt/fgbears-live/bin/stream-status.sh /usr/local/bin/fgbears-stream-status

# Legacy destination and audio-mastering entry points are deliberately absent.
rm -f /usr/local/bin/fgbears-rumble-relay /usr/local/bin/fgbears-configure-rumble /usr/local/bin/fgbears-normalize /usr/local/bin/fgbears-add-episode
rm -f /opt/fgbears-live/bin/normalize-library.sh /opt/fgbears-live/bin/normalize-resilient.sh /opt/fgbears-live/bin/add-episode.sh

install -m 0644 /opt/fgbears-live/systemd/fgbears-live.service /etc/systemd/system/fgbears-live.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-youtube-copy-relay.service /etc/systemd/system/fgbears-youtube-copy-relay.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.service /etc/systemd/system/fgbears-live-health.service
install -m 0644 /opt/fgbears-live/systemd/fgbears-live-health.timer /etc/systemd/system/fgbears-live-health.timer
if [[ -f /opt/fgbears-live/systemd/fgbears-news-refresh.service ]]; then install -m 0644 /opt/fgbears-live/systemd/fgbears-news-refresh.service /etc/systemd/system/fgbears-news-refresh.service; fi
if [[ -f /opt/fgbears-live/systemd/fgbears-news-refresh.timer ]]; then install -m 0644 /opt/fgbears-live/systemd/fgbears-news-refresh.timer /etc/systemd/system/fgbears-news-refresh.timer; fi

ENV_PATH=/etc/fgbears-live/stream.env
if [[ ! -e "$ENV_PATH" ]]; then install -o root -g fgbears -m 0640 /opt/fgbears-live/config/stream.env.example "$ENV_PATH"; fi
python3 - "$ENV_PATH" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
lines=p.read_text(encoding='utf-8').splitlines()
out=[]; seen=False
for line in lines:
    if line.startswith('YOUTUBE_COPY_LOCAL_UDP_URL='):
        if not seen: out.append('YOUTUBE_COPY_LOCAL_UDP_URL=udp://127.0.0.1:1940?pkt_size=1316'); seen=True
    else: out.append(line)
if not seen: out.append('YOUTUBE_COPY_LOCAL_UDP_URL=udp://127.0.0.1:1940?pkt_size=1316')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chown root:fgbears "$ENV_PATH"; chmod 0640 "$ENV_PATH"

retired_units=(
  fgbears-rumble-relay.service
  fgbears-rumble-studio-uplink.service
  fgbears-lovable-state-cache.service
  fgbears-youtube-v2.service fgbears-youtube-v2-health.service fgbears-youtube-v2-health.timer
  fgbears-youtube-v3.service fgbears-youtube-v3-source.service fgbears-youtube-v3-supervisor.service
  fgbears-youtube-output.service fgbears-youtube-relay.service fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service
  fgbears-youtube-dynamic-card.service fgbears-youtube-freeze-card-refresh.service fgbears-youtube-freeze-card-refresh.timer
  fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer
)
for unit in "${retired_units[@]}"; do systemctl disable --now "$unit" >/dev/null 2>&1 || true; done
systemctl daemon-reload
for unit in "${retired_units[@]}"; do systemctl mask "$unit" >/dev/null 2>&1 || true; done

systemctl enable fgbears-live.service fgbears-youtube-copy-relay.service >/dev/null
systemctl enable --now fgbears-live-health.timer >/dev/null
if systemctl cat fgbears-news-refresh.timer >/dev/null 2>&1; then systemctl enable --now fgbears-news-refresh.timer >/dev/null; fi

echo 'Installed current FGBears YouTube-only control files. Rumble, retired YouTube generations, and legacy audio mastering remain quarantined. No live media process was restarted.'

#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install-control.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ffmpeg ca-certificates curl jq python3 librsvg2-bin rsync

install -d -m 0755 /opt/fgbears-live
rsync -a "$SOURCE_DIR/" /opt/fgbears-live/
install -d -o fgbears -g fgbears -m 0755 /srv/fgbears-live/control /srv/fgbears-live/control/rendered

install -m 0755 /opt/fgbears-live/bin/sync-control.sh /usr/local/bin/fgbears-sync-control
install -m 0755 /opt/fgbears-live/bin/render-control-assets.sh /usr/local/bin/fgbears-render-control-assets
install -m 0755 /opt/fgbears-live/bin/validate-control.py /usr/local/bin/fgbears-validate-control

echo "Installed FGB live control tooling only. Existing fgbears-live.service was not changed or restarted."
echo "Run 'sudo -u fgbears fgbears-sync-control' only after the control branch is merged/approved."

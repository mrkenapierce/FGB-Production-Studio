#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

install -m 0755 "$ROOT/bin/lovable-audio-pipeline-v4.py" /usr/local/bin/fgbears-lovable-audio-pipeline
install -m 0755 "$ROOT/bin/audio-health-standard-v4.py" /usr/local/bin/fgbears-audio-health
install -m 0644 "$ROOT/systemd/fgbears-lovable-audio-sync.service" /etc/systemd/system/fgbears-lovable-audio-sync.service
install -m 0644 "$ROOT/systemd/fgbears-lovable-audio-sync.timer" /etc/systemd/system/fgbears-lovable-audio-sync.timer
systemctl daemon-reload

if [[ ${1:-} == '--enable' ]]; then
  systemctl enable --now fgbears-lovable-audio-sync.timer
fi

echo 'FGB audio standard v4 installed. 44.1 kHz AAC delivery is canonical; no loudness/dynamics processing is performed.'

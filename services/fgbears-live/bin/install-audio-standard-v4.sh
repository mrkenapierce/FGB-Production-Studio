#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

# Legacy 48 kHz preparation pathway remains quarantined under its historical
# executable/unit names. v4 uses distinct names so enabling the safe pathway
# cannot revive the legacy pathway by accident.
install -d -m 0755 /usr/local/lib/fgbears-live
install -m 0644 "$ROOT/bin/lovable-audio-pipeline-v4.py" /usr/local/lib/fgbears-live/lovable-audio-pipeline-v4.py
install -m 0755 "$ROOT/bin/lovable-audio-pipeline-v4-runner.py" /usr/local/bin/fgbears-lovable-audio-v4-sync
install -m 0755 "$ROOT/bin/audio-health-standard-v4.py" /usr/local/bin/fgbears-audio-health
install -m 0755 "$ROOT/bin/start-stream.sh" /usr/local/bin/fgbears-start-stream
install -m 0644 "$ROOT/systemd/fgbears-lovable-audio-v4-sync.service" /etc/systemd/system/fgbears-lovable-audio-v4-sync.service
install -m 0644 "$ROOT/systemd/fgbears-lovable-audio-v4-sync.timer" /etc/systemd/system/fgbears-lovable-audio-v4-sync.timer
systemctl daemon-reload

if [[ ${1:-} == '--enable' ]]; then
  systemctl enable --now fgbears-lovable-audio-v4-sync.timer
fi

echo 'FGB audio standard v4.1 installed: master-owned 44.1 kHz AAC clock, zero loudness/dynamics processing, isolated safe Lovable approval sync ready.'

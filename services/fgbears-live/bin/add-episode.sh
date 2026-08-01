#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -eq 1 ]] || { echo "Usage: add-episode.sh /path/to/episode.mp4" >&2; exit 64; }
SOURCE=$1
[[ -f "$SOURCE" ]] || { echo "Episode file not found: $SOURCE" >&2; exit 66; }

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
OUTPUT="$MEDIA_DIR/$(basename "${SOURCE%.*}").mp4"

/usr/local/bin/fgbears-normalize "$SOURCE" "$OUTPUT"
/usr/local/bin/fgbears-validate "$MEDIA_DIR"
/usr/local/bin/fgbears-rebuild-playlist

if systemctl is-enabled --quiet fgbears-live.service; then
  systemctl restart fgbears-live.service
fi
printf 'Episode installed and playlist activated: %s\n' "$OUTPUT"

#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -eq 1 ]] || { echo "Usage: add-episode-v3.sh /path/to/original.mp4" >&2; exit 64; }
SOURCE=$1
[[ -f "$SOURCE" ]] || { echo "Episode source not found: $SOURCE" >&2; exit 66; }

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
PREPARER=${FGB_PREPARE_V3:-/usr/local/bin/fgbears-prepare-v3}
VALIDATOR=${FGB_VALIDATE:-/usr/local/bin/fgbears-validate}
REBUILDER=${FGB_REBUILD_PLAYLIST:-/usr/local/bin/fgbears-rebuild-playlist}
[[ -x "$PREPARER" ]] || { echo "Clean v3 preparer unavailable: $PREPARER" >&2; exit 69; }
[[ -x "$VALIDATOR" ]] || { echo "Validator unavailable: $VALIDATOR" >&2; exit 69; }
[[ -x "$REBUILDER" ]] || { echo "Playlist rebuilder unavailable: $REBUILDER" >&2; exit 69; }

OUTPUT="$MEDIA_DIR/$(basename "${SOURCE%.*}").mp4"
WORK_DIR=${FGB_INGEST_WORK_DIR:-/srv/fgbears-live/audio-v3-work}
mkdir -p "$WORK_DIR" "$MEDIA_DIR"
CANDIDATE="$WORK_DIR/$(basename "$OUTPUT")"
rm -f "$CANDIDATE" "$CANDIDATE.audio-profile.json"

nice -n 15 ionice -c2 -n7 "$PREPARER" \
  --video-source "$SOURCE" \
  --audio-source "$SOURCE" \
  --output "$CANDIDATE" \
  --source-kind new_original

# Validate the candidate in isolation before touching production.
TMP_VALIDATE=$(mktemp -d /tmp/fgb-v3-validate.XXXXXX)
trap 'rm -rf "$TMP_VALIDATE"' EXIT
ln "$CANDIDATE" "$TMP_VALIDATE/$(basename "$OUTPUT")"
ln "$CANDIDATE.audio-profile.json" "$TMP_VALIDATE/$(basename "$OUTPUT").audio-profile.json"
"$VALIDATOR" "$TMP_VALIDATE"

# Atomic promotion. An already-open old inode continues playing undisturbed.
if [[ -e "$OUTPUT" ]]; then
  QDIR=/srv/fgbears-live/quarantine/replaced-production-audio-v2
  mkdir -p "$QDIR"
  [[ -e "$QDIR/$(basename "$OUTPUT")" ]] || ln "$OUTPUT" "$QDIR/$(basename "$OUTPUT")"
  [[ ! -e "$OUTPUT.audio-profile.json" || -e "$QDIR/$(basename "$OUTPUT").audio-profile.json" ]] || ln "$OUTPUT.audio-profile.json" "$QDIR/$(basename "$OUTPUT").audio-profile.json"
fi
mv -f "$CANDIDATE" "$OUTPUT"
mv -f "$CANDIDATE.audio-profile.json" "$OUTPUT.audio-profile.json"
"$VALIDATOR" "$MEDIA_DIR"
"$REBUILDER"
printf 'Episode admitted under fgb-clean-static-v3 without restarting the live master: %s\n' "$OUTPUT"

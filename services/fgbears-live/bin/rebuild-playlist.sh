#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
[[ -d "$MEDIA_DIR" ]] || { echo "Media directory does not exist: $MEDIA_DIR" >&2; exit 66; }

# Playlist admission policy: every production episode must pass the same
# canonical media and loudness-profile validation used by add-episode.sh.
# This prevents manually copied/unprofiled media from bypassing normalization.
#
# In an installed production tree validate-media.sh is executable. In a source
# checkout (including CI) the GitHub contents API can leave shell files readable
# but not executable, so invoke a readable local shell validator through bash
# instead of requiring an irrelevant file-mode mutation.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VALIDATOR=${VALIDATOR:-}
VALIDATOR_CMD=()
if [[ -n "$VALIDATOR" ]]; then
  if [[ -x "$VALIDATOR" ]]; then
    VALIDATOR_CMD=("$VALIDATOR")
  elif [[ -r "$VALIDATOR" && "$VALIDATOR" == *.sh ]]; then
    VALIDATOR_CMD=(bash "$VALIDATOR")
  else
    echo "Validator is unavailable or unreadable: $VALIDATOR" >&2
    exit 69
  fi
elif [[ -r "$SCRIPT_DIR/validate-media.sh" ]]; then
  VALIDATOR_CMD=(bash "$SCRIPT_DIR/validate-media.sh")
elif [[ -x /usr/local/bin/fgbears-validate ]]; then
  VALIDATOR_CMD=(/usr/local/bin/fgbears-validate)
else
  echo "FGB media validator is unavailable; refusing to rebuild playlist" >&2
  exit 69
fi
"${VALIDATOR_CMD[@]}" "$MEDIA_DIR"

mapfile -d '' files < <(find "$MEDIA_DIR" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -zV)
[[ ${#files[@]} -gt 0 ]] || { echo "No MP4 files found in $MEDIA_DIR" >&2; exit 65; }

mkdir -p "$(dirname "$PLAYLIST_FILE")"
tmp=$(mktemp "${PLAYLIST_FILE}.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf 'ffconcat version 1.0\n' > "$tmp"
for file in "${files[@]}"; do
  [[ "$file" != *"'"* ]] || { echo "Apostrophes are not supported in filenames: $file" >&2; exit 65; }
  printf "file '%s'\n" "$file" >> "$tmp"
done
chmod 0644 "$tmp"
mv -f "$tmp" "$PLAYLIST_FILE"
trap - EXIT
printf 'Playlist rebuilt with %d verified normalized episodes: %s\n' "${#files[@]}" "$PLAYLIST_FILE"

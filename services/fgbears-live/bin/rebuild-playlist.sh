#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
PLAYLIST_FILE=${PLAYLIST_FILE:-/srv/fgbears-live/playlist.ffconcat}
[[ -d "$MEDIA_DIR" ]] || { echo "Media directory does not exist: $MEDIA_DIR" >&2; exit 66; }

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
printf 'Playlist rebuilt with %d episodes: %s\n' "${#files[@]}" "$PLAYLIST_FILE"

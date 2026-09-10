#!/usr/bin/env bash
set -Eeuo pipefail

CONTROL_ROOT=${CONTROL_ROOT:-/srv/fgbears-live/control/current}
RENDERED_DIR=${RENDERED_DIR:-/srv/fgbears-live/control/rendered}
AUDIO_PLAYLIST=${AUDIO_PLAYLIST:-/srv/fgbears-live/playlist.ffconcat}
VISUAL_PLAYLIST=${VISUAL_PLAYLIST:-/srv/fgbears-live/control/visual-poc.ffconcat}
OUTPUT=${OUTPUT:-/srv/fgbears-live/control/poc-output.flv}
SCHEDULE="$CONTROL_ROOT/services/fgbears-live/control/schedule.json"

command -v jq >/dev/null || { echo "jq is required" >&2; exit 69; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 69; }
[[ -f "$SCHEDULE" ]] || { echo "Missing synchronized schedule: $SCHEDULE" >&2; exit 66; }
[[ -s "$AUDIO_PLAYLIST" ]] || { echo "Missing audio source playlist: $AUDIO_PLAYLIST" >&2; exit 66; }

mkdir -p "$(dirname "$VISUAL_PLAYLIST")"
tmp=$(mktemp "${VISUAL_PLAYLIST}.XXXXXX")
trap 'rm -f "$tmp"' EXIT
printf 'ffconcat version 1.0\n' > "$tmp"

count=0
while IFS= read -r id; do
  clip="$RENDERED_DIR/$id.mp4"
  [[ -f "$clip" ]] || { echo "Missing rendered visual clip: $clip" >&2; exit 66; }
  [[ "$clip" != *"'"* ]] || { echo "Apostrophes are unsupported in clip paths" >&2; exit 65; }
  printf "file '%s'\n" "$clip" >> "$tmp"
  count=$((count + 1))
done < <(jq -r '.items[] | select(.active == true) | .id' "$SCHEDULE")

[[ $count -gt 0 ]] || { echo "No active visual items" >&2; exit 65; }
mv -f "$tmp" "$VISUAL_PLAYLIST"
trap - EXIT

# POC ONLY: independently loop visual programming and the existing episode playlist,
# mapping visual video from input 0 and podcast audio from input 1.
# The default output is a local FLV file so this command cannot accidentally go live.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -re -stream_loop -1 -f concat -safe 0 -i "$VISUAL_PLAYLIST" \
  -re -stream_loop -1 -f concat -safe 0 -i "$AUDIO_PLAYLIST" \
  -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "$OUTPUT"

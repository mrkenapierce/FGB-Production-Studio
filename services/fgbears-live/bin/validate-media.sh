#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR=${1:-${MEDIA_DIR:-/srv/fgbears-live/media}}
[[ -d "$MEDIA_DIR" ]] || { echo "Media directory does not exist: $MEDIA_DIR" >&2; exit 66; }

failures=0
count=0
while IFS= read -r -d '' file; do
  count=$((count + 1))
  video=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt \
    -of json "$file" | jq -r '.streams[0] | [.codec_name, (.width|tostring), (.height|tostring), .r_frame_rate, .pix_fmt] | join("|")')
  audio=$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels \
    -of json "$file" | jq -r '.streams[0] | [.codec_name, .sample_rate, (.channels|tostring)] | join("|")')

  if [[ "$video" != "h264|1280|720|30/1|yuv420p" || "$audio" != "aac|48000|2" ]]; then
    echo "INVALID: $file" >&2
    echo "  video=$video" >&2
    echo "  audio=$audio" >&2
    failures=$((failures + 1))
  else
    echo "OK: $file"
  fi
done < <(find "$MEDIA_DIR" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -zV)

[[ $count -gt 0 ]] || { echo "No MP4 files found in $MEDIA_DIR" >&2; exit 65; }
[[ $failures -eq 0 ]] || exit 1

#!/usr/bin/env bash
set -Eeuo pipefail

SCHEDULE=${1:-/srv/fgbears-live/control/current/services/fgbears-live/control/schedule.json}
ROOT=${2:-/srv/fgbears-live/control/current}
OUTPUT=${3:-/srv/fgbears-live/control/rendered}

command -v jq >/dev/null || { echo "jq is required" >&2; exit 69; }
command -v rsvg-convert >/dev/null || { echo "rsvg-convert is required (package: librsvg2-bin)" >&2; exit 69; }
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 69; }

[[ -f "$SCHEDULE" ]] || { echo "Schedule not found: $SCHEDULE" >&2; exit 66; }
mkdir -p "$OUTPUT"

jq -c '.items[] | select(.active == true)' "$SCHEDULE" | while IFS= read -r item; do
  id=$(jq -r '.id' <<<"$item")
  asset=$(jq -r '.asset' <<<"$item")
  duration=$(jq -r '.duration_seconds' <<<"$item")
  source="$ROOT/$asset"
  [[ -f "$source" ]] || { echo "Missing creative for $id: $source" >&2; exit 66; }

  ext=${asset##*.}
  png="$OUTPUT/$id.png"
  mp4="$OUTPUT/$id.mp4"

  case "${ext,,}" in
    svg)
      rsvg-convert --width 1280 --height 720 "$source" > "$png"
      ;;
    png|jpg|jpeg|webp)
      ffmpeg -hide_banner -loglevel error -y -i "$source" -vf 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2' -frames:v 1 "$png"
      ;;
    *)
      echo "Unsupported creative extension for $id: $ext" >&2
      exit 65
      ;;
  esac

  ffmpeg -hide_banner -loglevel error -y \
    -loop 1 -framerate 30 -i "$png" \
    -t "$duration" \
    -c:v libx264 -preset veryfast -tune stillimage \
    -pix_fmt yuv420p -profile:v high -level 3.1 \
    -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
    -b:v 4M -maxrate 4M -bufsize 8M \
    -an -movflags +faststart "$mp4"

  echo "Rendered $id -> $mp4 (${duration}s)"
done

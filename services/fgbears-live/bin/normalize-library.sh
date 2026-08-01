#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: normalize-library.sh INPUT [OUTPUT]

Standardizes one owned/authorized episode for low-CPU 24/7 relay:
  1280x720, 30 fps CFR, H.264, AAC stereo 48 kHz, ~2.5 Mbps video.
USAGE
}

[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 64; }
INPUT=$1
[[ -f "$INPUT" ]] || { echo "Input does not exist: $INPUT" >&2; exit 66; }

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
OUTPUT=${2:-"$MEDIA_DIR/$(basename "${INPUT%.*}").mp4"}
mkdir -p "$(dirname "$OUTPUT")"
TMP_OUTPUT="${OUTPUT%.mp4}.partial.mp4"
trap 'rm -f "$TMP_OUTPUT"' EXIT

has_audio=0
if ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$INPUT" | grep -q .; then
  has_audio=1
fi

VIDEO_FILTER='scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p'
COMMON_VIDEO=(
  -c:v libx264 -preset veryfast -profile:v high -level 4.0
  -b:v 2500k -maxrate 2500k -bufsize 5000k
  -g 60 -keyint_min 60 -sc_threshold 0 -pix_fmt yuv420p
  -threads 2
)
COMMON_AUDIO=(-c:a aac -b:a 128k -ar 48000 -ac 2)

if [[ $has_audio -eq 1 ]]; then
  ffmpeg -hide_banner -y -loglevel warning \
    -i "$INPUT" \
    -map 0:v:0 -map 0:a:0 \
    -vf "$VIDEO_FILTER" \
    "${COMMON_VIDEO[@]}" \
    "${COMMON_AUDIO[@]}" \
    -af 'aresample=async=1:first_pts=0' \
    -shortest -movflags +faststart -map_metadata -1 \
    "$TMP_OUTPUT"
else
  ffmpeg -hide_banner -y -loglevel warning \
    -i "$INPUT" \
    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 \
    -map 0:v:0 -map 1:a:0 \
    -vf "$VIDEO_FILTER" \
    "${COMMON_VIDEO[@]}" \
    "${COMMON_AUDIO[@]}" \
    -shortest -movflags +faststart -map_metadata -1 \
    "$TMP_OUTPUT"
fi

mv -f "$TMP_OUTPUT" "$OUTPUT"
trap - EXIT
printf 'Normalized: %s\n' "$OUTPUT"

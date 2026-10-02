#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE_DIR="${FGB_ARCHIVE_DIR:-/archive}"
SEGMENT_SECONDS="${FGB_ARCHIVE_SEGMENT_SECONDS:-3600}"
TIMEZONE="${FGB_ARCHIVE_TIMEZONE:-America/Chicago}"
INPUT_URL="${FGB_ARCHIVE_LOCAL_UDP_URL:-udp://127.0.0.1:1944?fifo_size=1000000&overrun_nonfatal=1&reuse=1}"
MIN_FREE_GB="${FGB_ARCHIVE_MIN_FREE_GB:-8}"
LOGLEVEL="${FFMPEG_LOGLEVEL:-warning}"

[[ "$SEGMENT_SECONDS" =~ ^[0-9]+$ ]] && (( SEGMENT_SECONDS >= 60 )) || {
  echo "FGB_ARCHIVE_SEGMENT_SECONDS must be an integer >= 60" >&2
  exit 78
}
[[ "$MIN_FREE_GB" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
  echo "FGB_ARCHIVE_MIN_FREE_GB must be numeric" >&2
  exit 78
}
[[ "$INPUT_URL" == udp://127.0.0.1:* ]] || {
  echo "Archive input must remain on loopback" >&2
  exit 78
}

mkdir -p "$ARCHIVE_DIR/hourly" "$ARCHIVE_DIR/final" "$ARCHIVE_DIR/state"
export TZ="$TIMEZONE"

free_kb=$(df -Pk "$ARCHIVE_DIR" | awk 'NR==2 {print $4}')
min_free_kb=$(awk -v gb="$MIN_FREE_GB" 'BEGIN {printf "%.0f", gb*1024*1024}')
if (( free_kb < min_free_kb )); then
  echo "ARCHIVE_RECORDER_LOW_DISK=true free_kb=$free_kb minimum_kb=$min_free_kb" >&2
  exit 75
fi

# Include the UTC offset in each filename so the repeated 01:00 hour on the
# November DST transition cannot overwrite the first copy of that hour.
output="$ARCHIVE_DIR/hourly/live-%Y%m%d-%H%M%S-%z.ts"

echo "ARCHIVE_RECORDER_STARTED=true"
echo "ARCHIVE_RECORDER_SEGMENT_SECONDS=$SEGMENT_SECONDS"
echo "ARCHIVE_RECORDER_TIMEZONE=$TIMEZONE"

exec ffmpeg \
  -hide_banner -nostdin -loglevel "$LOGLEVEL" \
  -fflags +genpts+discardcorrupt \
  -probesize 10000000 -analyzeduration 10000000 \
  -i "$INPUT_URL" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f segment \
  -segment_time "$SEGMENT_SECONDS" \
  -segment_atclocktime 1 \
  -reset_timestamps 1 \
  -strftime 1 \
  -segment_format mpegts \
  "$output"

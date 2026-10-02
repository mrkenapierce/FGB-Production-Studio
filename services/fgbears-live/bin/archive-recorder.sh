#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${FGB_ARCHIVE_LOCAL_UDP_URL:=udp://127.0.0.1:1944?pkt_size=1316}"
: "${FGB_ARCHIVE_DIR:=/srv/fgbears-live/archive}"
: "${FGB_ARCHIVE_SEGMENT_SECONDS:=120}"
: "${FGB_ARCHIVE_MODE:=test}"
: "${FGB_ARCHIVE_TIMEZONE:=America/Chicago}"
: "${FGB_ARCHIVE_MIN_FREE_GB:=5}"
: "${FFMPEG_LOGLEVEL:=warning}"

[[ "$FGB_ARCHIVE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "FGB_ARCHIVE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
[[ "$FGB_ARCHIVE_SEGMENT_SECONDS" =~ ^[0-9]+$ ]] && (( FGB_ARCHIVE_SEGMENT_SECONDS >= 60 )) || {
  echo "FGB_ARCHIVE_SEGMENT_SECONDS must be an integer >= 60." >&2
  exit 78
}
[[ "$FGB_ARCHIVE_MODE" == "test" || "$FGB_ARCHIVE_MODE" == "prod" ]] || {
  echo "FGB_ARCHIVE_MODE must be test or prod." >&2
  exit 78
}
[[ "$FGB_ARCHIVE_MIN_FREE_GB" =~ ^[0-9]+([.][0-9]+)?$ ]] || {
  echo "FGB_ARCHIVE_MIN_FREE_GB must be numeric." >&2
  exit 78
}

mkdir -p "$FGB_ARCHIVE_DIR" "$FGB_ARCHIVE_DIR/state"
export TZ="$FGB_ARCHIVE_TIMEZONE"

free_kb=$(df -Pk "$FGB_ARCHIVE_DIR" | awk 'NR==2 {print $4}')
min_free_kb=$(awk -v gb="$FGB_ARCHIVE_MIN_FREE_GB" 'BEGIN {printf "%.0f", gb*1024*1024}')
if (( free_kb < min_free_kb )); then
  echo "Archive recorder refusing to start: free disk space is below ${FGB_ARCHIVE_MIN_FREE_GB} GiB." >&2
  exit 75
fi

LOCAL_BASE=${FGB_ARCHIVE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"

if [[ "$FGB_ARCHIVE_MODE" == "prod" ]]; then
  prefix="live"
  clock_args=(-segment_atclocktime 1)
else
  prefix="test"
  clock_args=()
fi

output="$FGB_ARCHIVE_DIR/${prefix}-%Y%m%d-%H%M%S.mp4"

echo "ARCHIVE_RECORDER_MODE=$FGB_ARCHIVE_MODE"
echo "ARCHIVE_RECORDER_SEGMENT_SECONDS=$FGB_ARCHIVE_SEGMENT_SECONDS"
echo "ARCHIVE_RECORDER_DIR=$FGB_ARCHIVE_DIR"

exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts+discardcorrupt -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f segment \
  -segment_time "$FGB_ARCHIVE_SEGMENT_SECONDS" \
  "${clock_args[@]}" \
  -reset_timestamps 1 \
  -strftime 1 \
  -segment_format mp4 \
  -segment_format_options movflags=+faststart \
  "$output"

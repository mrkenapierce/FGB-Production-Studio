#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_V3_LOCAL_UDP_URL:=udp://127.0.0.1:1950?pkt_size=1316}"
: "${YOUTUBE_V3_RUNTIME_DIR:=/run/fgbears-youtube-v3}"
: "${YOUTUBE_V3_HLS_TIME:=2}"
: "${YOUTUBE_V3_HLS_LIST_SIZE:=15}"

[[ "$YOUTUBE_V3_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "v3 input must be loopback UDP" >&2; exit 78; }
BASE=${YOUTUBE_V3_LOCAL_UDP_URL%%\?*}
INPUT="${BASE}?fifo_size=2000000&overrun_nonfatal=1&reuse=1"
ROOT="$YOUTUBE_V3_RUNTIME_DIR/source"
PLAYLIST="$ROOT/live.m3u8"
SEGMENT="$ROOT/seg-%09d.ts"

rm -rf "$ROOT"
install -d -m750 "$ROOT"

exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt \
  -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size 4096 -i "$INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c copy \
  -f hls \
  -hls_time "$YOUTUBE_V3_HLS_TIME" \
  -hls_list_size "$YOUTUBE_V3_HLS_LIST_SIZE" \
  -hls_delete_threshold 3 \
  -hls_segment_type mpegts \
  -hls_flags delete_segments+independent_segments+program_date_time+temp_file \
  -hls_segment_filename "$SEGMENT" \
  "$PLAYLIST"

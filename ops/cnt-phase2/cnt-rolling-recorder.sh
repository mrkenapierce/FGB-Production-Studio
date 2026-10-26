#!/usr/bin/env bash
# CNT rolling recorder. NOT INSTALLED. CNT only; never reads or writes FGB paths.
#
# Records the CNT program from the loopback MPEG-TS tap that run-cnt.sh emits
# when CNT_ARCHIVE_TAP is set (stream copy, no second encode, no CPU-heavy work)
# into clock-aligned segments:
#     $CNT_ARCHIVE_DIR/rolling/live-YYYYMMDD-HHMMSS-±HHMM.ts
# The same naming as the FGB production recorder, so episode-cutter.sh and
# cnt-daily-recorder.sh read both channels with one parser.
#
# Hard disk stop: a watchdog checks free space every 20 s. Below
# CNT_MIN_FREE_GB (default 8) it stops ONLY its own ffmpeg, writes
# state/low_disk, and resumes only after free space is back above the minimum
# plus 2 GB. It never deletes anything; deletion is cnt-archive-retention.sh,
# which honours holds and defaults to dry-run.
# Never touches the live CNT stream: if this recorder stops, the YouTube
# output continues (the tee tap uses onfail=ignore).
set -uo pipefail
DIR="${CNT_ARCHIVE_DIR:-/cnt-archive}"
TAP="${CNT_ARCHIVE_TAP_INPUT:-udp://127.0.0.1:24010?fifo_size=1000000&overrun_nonfatal=1&reuse=1}"
SEG="${CNT_SEGMENT_SECONDS:-600}"
MIN_GB="${CNT_MIN_FREE_GB:-8}"
TZ_NAME="${CNT_ARCHIVE_TIMEZONE:-America/Chicago}"
[[ "$TAP" == udp://127.0.0.1:* ]] || { echo "CNT tap must stay on loopback" >&2; exit 78; }
[[ "$SEG" =~ ^[0-9]+$ ]] && [ "$SEG" -ge 60 ] && [ "$SEG" -le 3600 ] || { echo "CNT_SEGMENT_SECONDS 60..3600" >&2; exit 78; }
case "$DIR" in /srv/fgb-archive*|/archive|/archive/*) echo "refusing FGB path" >&2; exit 78 ;; esac
mkdir -p "$DIR/rolling" "$DIR/state"
export TZ="$TZ_NAME"
log() { echo "[$(date -u +%FT%TZ)] [cnt-rolling] $*"; }
free_kb() { df -Pk "$DIR" | awk 'NR==2 {print $4}'; }
min_kb() { awk -v g="$1" 'BEGIN{printf "%.0f", g*1024*1024}'; }

FF=""
start() {
  ffmpeg -hide_banner -nostdin -loglevel warning -fflags +genpts+discardcorrupt \
    -probesize 10000000 -analyzeduration 10000000 -i "$TAP" -map 0:v:0 -map 0:a:0 -c copy \
    -f segment -segment_time "$SEG" -segment_atclocktime 1 -reset_timestamps 1 -strftime 1 \
    -segment_format mpegts "$DIR/rolling/live-%Y%m%d-%H%M%S-%z.ts" &
  FF=$!; log "recording pid $FF segment=${SEG}s"
}
stop() { [ -n "$FF" ] && kill "$FF" 2>/dev/null; wait "$FF" 2>/dev/null; FF=""; }
trap 'stop; exit 0' TERM INT

if [ "${1:-}" = "--preflight" ]; then
  f=$(free_kb); [ "$f" -ge "$(min_kb "$MIN_GB")" ] && { echo "PREFLIGHT_OK free_kb=$f"; exit 0; }
  echo "PREFLIGHT_BLOCKED free_kb=$f minimum_gb=$MIN_GB"; exit 75
fi

while true; do
  f=$(free_kb)
  if [ "$f" -lt "$(min_kb "$MIN_GB")" ]; then
    [ -n "$FF" ] && { log "LOW DISK free_kb=$f < ${MIN_GB}GB: stopping recording (nothing deleted)"; stop; }
    date -u +%FT%TZ > "$DIR/state/low_disk"
  elif [ -z "$FF" ] && [ "$f" -ge "$(min_kb "$(awk -v g="$MIN_GB" 'BEGIN{print g+2}')")" ]; then
    rm -f "$DIR/state/low_disk"; start
  elif [ -n "$FF" ] && ! kill -0 "$FF" 2>/dev/null; then
    log "ffmpeg exited; restarting in 5 s"; FF=""; sleep 5; continue
  fi
  sleep 20
done
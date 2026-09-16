#!/usr/bin/env bash
set -Eeuo pipefail

PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
TIMEOUT_SECONDS=${MASTER_MEDIA_READY_TIMEOUT_SECONDS:-30}
MIN_ADVANCE_US=${MASTER_MEDIA_READY_MIN_ADVANCE_US:-250000}

[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid MASTER_MEDIA_READY_TIMEOUT_SECONDS=$TIMEOUT_SECONDS" >&2; exit 78; }
[[ "$MIN_ADVANCE_US" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid MASTER_MEDIA_READY_MIN_ADVANCE_US=$MIN_ADVANCE_US" >&2; exit 78; }

started_epoch=$(date +%s)
deadline=$((SECONDS + TIMEOUT_SECONDS))
last_value=""

read_progress_us() {
  [[ -s "$PROGRESS_FILE" ]] || return 1
  awk -F= '
    $1 == "out_time_us" { value=$2 }
    END {
      if (value ~ /^[0-9]+$/) print value
      else exit 1
    }
  ' "$PROGRESS_FILE"
}

while (( SECONDS < deadline )); do
  if [[ -s "$PROGRESS_FILE" ]]; then
    mtime=$(stat -c %Y "$PROGRESS_FILE" 2>/dev/null || echo 0)
    value=$(read_progress_us 2>/dev/null || true)

    # Requiring an update at or after this helper started prevents a stale
    # pre-restart progress file from satisfying the gate.
    if [[ "$mtime" =~ ^[0-9]+$ ]] && (( mtime >= started_epoch )) && [[ "$value" =~ ^[0-9]+$ ]] && (( value > 0 )); then
      if [[ "$last_value" =~ ^[0-9]+$ ]] && (( value >= last_value + MIN_ADVANCE_US )); then
        echo "MASTER_MEDIA_READY=PASS progress_us=$value"
        exit 0
      fi
      last_value=$value
    fi
  fi
  sleep 1
done

echo "MASTER_MEDIA_READY=FAIL timeout_seconds=$TIMEOUT_SECONDS progress_file=$PROGRESS_FILE last_progress_us=${last_value:-none}" >&2
exit 75

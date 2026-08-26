#!/usr/bin/env bash
set -Eeuo pipefail

PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
BREAKER_FILE=${FFMPEG_RESTART_BREAKER_FILE:-/srv/fgbears-live/health/restart-breaker}
SAMPLE_SECONDS=${STREAM_STATUS_SAMPLE_SECONDS:-20}
WARN_SPEED=${STREAM_STATUS_WARN_SPEED:-0.95}
STALE_SECONDS=${STREAM_STATUS_STALE_SECONDS:-90}
NEWS_STATUS_FILE=${BEARS_NEWS_REFRESH_STATUS_FILE:-/srv/fgbears-live/runtime/bears-news-refresh-status.env}
NEWS_FEED_FILE=${BEARS_NEWS_LOCAL_FEED_FILE:-/srv/fgbears-live/runtime/fgb-bears-news.xml}
NEWS_ACTIVE_FILE=${BEARS_NEWS_ACTIVE_FILE:-/srv/fgbears-live/runtime/bears-news-active}
NEWS_STALE_SECONDS=${BEARS_NEWS_STALE_SECONDS:-1200}

if [[ ${1:-} == "--sample-seconds" ]]; then
  SAMPLE_SECONDS=${2:-}
fi
if [[ ! "$SAMPLE_SECONDS" =~ ^[0-9]+$ ]] || (( SAMPLE_SECONDS < 5 || SAMPLE_SECONDS > 60 )); then
  echo 'Sample duration must be between 5 and 60 seconds.' >&2
  exit 64
fi

now=$(date +%s)
service_active=$(systemctl is-active fgbears-live.service 2>/dev/null || true)
main_pid=$(systemctl show fgbears-live.service -p MainPID --value 2>/dev/null || true)
restart_count=$(systemctl show fgbears-live.service -p NRestarts --value 2>/dev/null || true)
service_uptime=0
if [[ "$main_pid" =~ ^[1-9][0-9]*$ ]]; then
  service_uptime=$(ps -o etimes= -p "$main_pid" 2>/dev/null | tr -d ' ' || true)
fi
[[ "$service_uptime" =~ ^[0-9]+$ ]] || service_uptime=0
[[ "$restart_count" =~ ^[0-9]+$ ]] || restart_count=0

ffmpeg_pid=$(pgrep -o ffmpeg 2>/dev/null || true)
encoder_cpu=0
if [[ "$ffmpeg_pid" =~ ^[1-9][0-9]*$ ]]; then
  encoder_cpu=$(ps -o %cpu= -p "$ffmpeg_pid" 2>/dev/null | tr -d ' ' || true)
fi
[[ "$encoder_cpu" =~ ^[0-9]+([.][0-9]+)?$ ]] || encoder_cpu=0

progress_age=-1
out_time_us=""
if [[ -s "$PROGRESS_FILE" ]]; then
  progress_updated=$(stat -c %Y "$PROGRESS_FILE")
  progress_age=$((now - progress_updated))
  out_time_us=$(sed -n 's/^out_time_us=\([0-9][0-9]*\)$/\1/p' "$PROGRESS_FILE" | tail -n 1)
fi

interval_speed="NA"
sample_result="UNAVAILABLE"
if [[ "$out_time_us" =~ ^[0-9]+$ ]]; then
  first_epoch=$now
  first_media=$out_time_us
  sleep "$SAMPLE_SECONDS"
  second_epoch=$(date +%s)
  second_media=$(sed -n 's/^out_time_us=\([0-9][0-9]*\)$/\1/p' "$PROGRESS_FILE" 2>/dev/null | tail -n 1)
  if [[ "$second_media" =~ ^[0-9]+$ ]] && (( second_media >= first_media && second_epoch > first_epoch )); then
    interval_speed=$(awk -v start="$first_media" -v finish="$second_media" -v seconds="$((second_epoch - first_epoch))" \
      'BEGIN { printf "%.3f", (finish-start)/1000000/seconds }')
    sample_result="MEASURED"
  else
    sample_result="RESET_OR_MISSING"
  fi
fi

status="OK"
reason="HEALTHY"
breaker_open=0
if [[ -s "$BREAKER_FILE" ]]; then
  status="CRITICAL"
  reason="RESTART_BREAKER_OPEN"
  breaker_open=1
elif [[ "$service_active" != "active" ]]; then
  status="CRITICAL"
  reason="SERVICE_NOT_ACTIVE"
elif [[ ! "$ffmpeg_pid" =~ ^[1-9][0-9]*$ ]]; then
  status="CRITICAL"
  reason="FFMPEG_NOT_RUNNING"
elif (( progress_age < 0 )); then
  status="CRITICAL"
  reason="PROGRESS_MISSING"
elif (( progress_age > STALE_SECONDS )); then
  status="CRITICAL"
  reason="PROGRESS_STALE"
elif [[ "$sample_result" == "RESET_OR_MISSING" ]]; then
  status="CRITICAL"
  reason="PROGRESS_RESET_DURING_SAMPLE"
elif [[ "$sample_result" == "MEASURED" ]] && ! awk -v value="$interval_speed" -v minimum="$WARN_SPEED" \
  'BEGIN { exit !(value >= minimum) }'; then
  status="WARN"
  reason="ENCODER_BELOW_REALTIME"
fi

available_memory_mb=$(awk '/^MemAvailable:/ { printf "%.0f", $2 / 1024 }' /proc/meminfo)
load_1m=$(awk '{ print $1 }' /proc/loadavg)

news_refresh_status="NOT_INITIALIZED"
news_scan_epoch=0
news_scan_age=-1
news_item_count=0
news_feed_bytes=0
news_ribbon_active=0
if [[ -s "$NEWS_STATUS_FILE" ]]; then
  news_refresh_status=$(sed -n 's/^STATUS=\([A-Z][A-Z]*\)$/\1/p' "$NEWS_STATUS_FILE" | tail -n 1)
  news_scan_epoch=$(sed -n 's/^LAST_SCAN_EPOCH=\([0-9][0-9]*\)$/\1/p' "$NEWS_STATUS_FILE" | tail -n 1)
  news_item_count=$(sed -n 's/^ITEM_COUNT=\([0-9][0-9]*\)$/\1/p' "$NEWS_STATUS_FILE" | tail -n 1)
  [[ "$news_scan_epoch" =~ ^[0-9]+$ ]] || news_scan_epoch=0
  [[ "$news_item_count" =~ ^[0-9]+$ ]] || news_item_count=0
  if (( news_scan_epoch > 0 )); then
    news_scan_age=$(( $(date +%s) - news_scan_epoch ))
  fi
fi
if [[ -s "$NEWS_FEED_FILE" ]]; then
  news_feed_bytes=$(stat -c %s "$NEWS_FEED_FILE" 2>/dev/null || echo 0)
fi
if [[ -r "$NEWS_ACTIVE_FILE" ]] && [[ $(tr -d '[:space:]' < "$NEWS_ACTIVE_FILE") == "1" ]]; then
  news_ribbon_active=1
fi

if [[ "$status" == "OK" ]]; then
  if [[ "$news_refresh_status" == "ERROR" ]]; then
    status="WARN"
    reason="NEWS_REFRESH_ERROR"
  elif (( news_scan_age < 0 )); then
    status="WARN"
    reason="NEWS_REFRESH_NOT_INITIALIZED"
  elif (( news_scan_age > NEWS_STALE_SECONDS )); then
    status="WARN"
    reason="NEWS_REFRESH_STALE"
  elif (( news_feed_bytes <= 0 )); then
    status="WARN"
    reason="NEWS_FEED_MISSING"
  elif (( news_ribbon_active == 0 )); then
    status="WARN"
    reason="NEWS_RIBBON_INACTIVE"
  fi
fi

printf 'OVERALL_STATUS=%s\n' "$status"
printf 'REASON=%s\n' "$reason"
printf 'CHECKED_AT_EPOCH=%s\n' "$(date +%s)"
printf 'SERVICE_ACTIVE=%s\n' "${service_active:-unknown}"
printf 'SERVICE_UPTIME_SECONDS=%s\n' "$service_uptime"
printf 'SYSTEMD_RESTARTS=%s\n' "$restart_count"
printf 'RESTART_BREAKER_OPEN=%s\n' "$breaker_open"
printf 'FFMPEG_PID=%s\n' "${ffmpeg_pid:-0}"
printf 'ENCODER_CPU_PERCENT=%s\n' "$encoder_cpu"
printf 'PROGRESS_AGE_SECONDS=%s\n' "$progress_age"
printf 'INTERVAL_SPEED=%s\n' "$interval_speed"
printf 'SAMPLE_RESULT=%s\n' "$sample_result"
printf 'AVAILABLE_MEMORY_MB=%s\n' "$available_memory_mb"
printf 'LOAD_1M=%s\n' "$load_1m"
printf 'NEWS_REFRESH_STATUS=%s\n' "$news_refresh_status"
printf 'NEWS_SCAN_AGE_SECONDS=%s\n' "$news_scan_age"
printf 'NEWS_ITEM_COUNT=%s\n' "$news_item_count"
printf 'NEWS_FEED_BYTES=%s\n' "$news_feed_bytes"
printf 'NEWS_RIBBON_ACTIVE=%s\n' "$news_ribbon_active"

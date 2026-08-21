#!/usr/bin/env bash
set -Eeuo pipefail

PROGRESS_FILE=${FFMPEG_PROGRESS_FILE:-/srv/fgbears-live/logs/ffmpeg-progress.log}
BREAKER_FILE=${FFMPEG_RESTART_BREAKER_FILE:-/srv/fgbears-live/health/restart-breaker}
SAMPLE_SECONDS=${STREAM_STATUS_SAMPLE_SECONDS:-20}
WARN_SPEED=${STREAM_STATUS_WARN_SPEED:-0.95}
STALE_SECONDS=${STREAM_STATUS_STALE_SECONDS:-90}
ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}

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

central_hm=$(TZ=America/Chicago date +%H%M)
central_hm=$((10#$central_hm))
social_window=0
(( central_hm >= 900 && central_hm < 1700 )) && social_window=1

social_state() {
  local platform=$1 enabled_key=$2 service="fgbears-${platform}-relay.service"
  local enabled=0 active=0 socket=0 pid
  [[ -r "$ENV_FILE" ]] && grep -Eq "^${enabled_key}=(1|true|yes|on)$" "$ENV_FILE" && enabled=1
  systemctl is-active --quiet "$service" && active=1 || true
  pid=$(systemctl show -p MainPID --value "$service" 2>/dev/null || true)
  if (( active == 1 )) && [[ "$pid" =~ ^[1-9][0-9]*$ ]]; then
    sudo ss -ntpH state established 2>/dev/null | grep "pid=$pid" | grep -vE '127\.0\.0\.1|\[::1\]' | grep -q ':443' && socket=1 || true
  fi
  printf '%s %s %s\n' "$enabled" "$active" "$socket"
}

read -r x_enabled x_active x_socket < <(social_state x X_RELAY_ENABLED)
read -r facebook_enabled facebook_active facebook_socket < <(social_state facebook FACEBOOK_RELAY_ENABLED)
read -r instagram_enabled instagram_active instagram_socket < <(social_state instagram INSTAGRAM_RELAY_ENABLED)

if (( social_window == 1 )); then
  for platform in x facebook instagram; do
    [[ "$status" == "OK" ]] || break
    eval "enabled=\${${platform}_enabled} active=\${${platform}_active} socket=\${${platform}_socket}"
    if (( enabled == 1 && active == 0 )); then
      status="WARN"
      reason="${platform^^}_RELAY_INACTIVE"
      break
    fi
    if (( enabled == 1 && socket == 0 )); then
      status="WARN"
      reason="${platform^^}_INGEST_NOT_ESTABLISHED"
      break
    fi
  done
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
printf 'SOCIAL_WINDOW_ACTIVE=%s\n' "$social_window"
printf 'X_ENABLED=%s\nX_RELAY_ACTIVE=%s\nX_INGEST_SOCKET=%s\n' "$x_enabled" "$x_active" "$x_socket"
printf 'FACEBOOK_ENABLED=%s\nFACEBOOK_RELAY_ACTIVE=%s\nFACEBOOK_INGEST_SOCKET=%s\n' "$facebook_enabled" "$facebook_active" "$facebook_socket"
printf 'INSTAGRAM_ENABLED=%s\nINSTAGRAM_RELAY_ACTIVE=%s\nINSTAGRAM_INGEST_SOCKET=%s\n' "$instagram_enabled" "$instagram_active" "$instagram_socket"

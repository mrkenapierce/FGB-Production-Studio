#!/usr/bin/env bash
# FGBears YouTube-only audio/transport watchdog.
#
# This watchdog never restarts the shared master encoder or the Rumble relay.
# It verifies the exact YouTube-bound source, the canonical copy-remux process,
# the RTMPS socket, and recent timestamp errors. Recoverable YouTube-only faults
# restart only fgbears-youtube-relay.service with a circuit breaker.
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
RELAY_SERVICE=${FGB_YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
MASTER_SERVICE=${FGB_MASTER_SERVICE:-fgbears-live.service}
RUMBLE_SERVICE=${FGB_RUMBLE_SERVICE:-fgbears-rumble-relay.service}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
STATE_DIR=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATE_DIR:-/srv/fgbears-live/health/youtube-audio}
STATUS_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATUS_FILE:-$STATE_DIR/status.env}
WARNING_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_WARNING_FILE:-$STATE_DIR/warning.env}
LAST_CHECK_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_LAST_CHECK_FILE:-$STATE_DIR/last-check-epoch}
RESTART_HISTORY_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_RESTART_HISTORY_FILE:-$STATE_DIR/restart-history}
SOCKET_FAILURE_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_SOCKET_FAILURE_FILE:-$STATE_DIR/socket-failures}
CAPTURE_SECONDS=${FGB_YOUTUBE_AUDIO_WATCHDOG_CAPTURE_SECONDS:-8}
RESTART_BUDGET=${FGB_YOUTUBE_AUDIO_WATCHDOG_RESTART_BUDGET:-2}
RESTART_WINDOW_SECONDS=${FGB_YOUTUBE_AUDIO_WATCHDOG_RESTART_WINDOW_SECONDS:-1800}
SOCKET_FAILURES_BEFORE_RESTART=${FGB_YOUTUBE_AUDIO_WATCHDOG_SOCKET_FAILURES_BEFORE_RESTART:-2}

mkdir -p "$STATE_DIR"

log() {
  logger -t fgbears-youtube-audio-watchdog -- "$*"
  printf '%s\n' "$*" >&2
}

pid_of() {
  systemctl show -p MainPID --value "$1" 2>/dev/null || printf '0'
}

cmdline_of() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ && -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline"
}

canonical_relay_process() {
  local pid=$1 args
  args=$(cmdline_of "$pid") || return 1
  [[ "$args" == *"ffmpeg"* ]] || return 1
  [[ "$args" == *" -c copy "* ]] || return 1
  [[ "$args" == *"udp://127.0.0.1:1939"* ]] || return 1
  [[ "$args" == *"rtmps://a.rtmps.youtube.com/"* || "$args" == *"rtmp://"* ]] || return 1
  [[ "$args" != *"youtube-stream-router"* ]] || return 1
  [[ "$args" != *"gst-launch"* ]] || return 1
  [[ "$args" != *"libx264"* ]] || return 1
  [[ "$args" != *" -c:a aac"* ]] || return 1
  return 0
}

rtmps_socket_ok() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | grep -F "pid=$pid" | grep -Eq ':[4]43([[:space:]]|$)'
}

write_status() {
  local state=$1 reason=$2 repaired=${3:-no} now temporary
  now=$(date +%s)
  temporary="${STATUS_FILE}.partial"
  {
    printf 'checked_epoch=%s\n' "$now"
    printf 'state=%s\n' "$state"
    printf 'reason=%s\n' "$reason"
    printf 'repaired=%s\n' "$repaired"
    printf 'youtube_pid=%s\n' "$(pid_of "$RELAY_SERVICE")"
    printf 'master_pid=%s\n' "$(pid_of "$MASTER_SERVICE")"
    printf 'rumble_pid=%s\n' "$(pid_of "$RUMBLE_SERVICE")"
  } > "$temporary"
  mv -f "$temporary" "$STATUS_FILE"
}

restart_budget_available() {
  local now cutoff temporary count
  now=$(date +%s)
  cutoff=$((now - RESTART_WINDOW_SECONDS))
  temporary="${RESTART_HISTORY_FILE}.partial"
  if [[ -s "$RESTART_HISTORY_FILE" ]]; then
    awk -v cutoff="$cutoff" '$1 >= cutoff { print $1 }' "$RESTART_HISTORY_FILE" > "$temporary"
  else
    : > "$temporary"
  fi
  mv -f "$temporary" "$RESTART_HISTORY_FILE"
  count=$(wc -l < "$RESTART_HISTORY_FILE")
  (( count < RESTART_BUDGET ))
}

record_restart() {
  date +%s >> "$RESTART_HISTORY_FILE"
}

attempt_repair() {
  local reason=$1 master_before rumble_before relay_after
  if ! restart_budget_available; then
    log "YouTube relay recovery suppressed by circuit breaker; reason=$reason"
    printf 'epoch=%s reason=%s circuit_breaker=open\n' "$(date +%s)" "$reason" > "$WARNING_FILE"
    write_status FAIL "${reason}_CIRCUIT_OPEN" no
    return 1
  fi

  master_before=$(pid_of "$MASTER_SERVICE")
  rumble_before=$(pid_of "$RUMBLE_SERVICE")
  record_restart
  log "Restarting isolated YouTube relay only; reason=$reason"
  systemctl reset-failed "$RELAY_SERVICE" || true
  systemctl restart "$RELAY_SERVICE"

  for _ in {1..40}; do
    if systemctl is-active --quiet "$RELAY_SERVICE"; then
      relay_after=$(pid_of "$RELAY_SERVICE")
      if canonical_relay_process "$relay_after" && rtmps_socket_ok "$relay_after"; then
        if [[ "$master_before" =~ ^[1-9][0-9]*$ ]]; then
          [[ "$(pid_of "$MASTER_SERVICE")" == "$master_before" ]] || {
            log "SAFETY FAILURE: master PID changed during YouTube-only recovery."
            write_status FAIL MASTER_PID_CHANGED no
            return 1
          }
        fi
        if [[ "$rumble_before" =~ ^[1-9][0-9]*$ ]]; then
          [[ "$(pid_of "$RUMBLE_SERVICE")" == "$rumble_before" ]] || {
            log "SAFETY FAILURE: Rumble PID changed during YouTube-only recovery."
            write_status FAIL RUMBLE_PID_CHANGED no
            return 1
          }
        fi
        rm -f "$SOCKET_FAILURE_FILE" "$WARNING_FILE"
        write_status OK "$reason" yes
        log "YouTube relay recovered without restarting master or Rumble."
        return 0
      fi
    fi
    sleep 0.5
  done

  printf 'epoch=%s reason=%s recovery=failed\n' "$(date +%s)" "$reason" > "$WARNING_FILE"
  write_status FAIL "${reason}_RECOVERY_FAILED" no
  log "YouTube relay recovery did not pass process/socket verification."
  return 1
}

recent_timestamp_errors() {
  local now last start count
  now=$(date +%s)
  last=$((now - 90))
  if [[ -s "$LAST_CHECK_FILE" ]]; then
    start=$(cat "$LAST_CHECK_FILE" 2>/dev/null || true)
    if [[ "$start" =~ ^[0-9]+$ && "$start" -lt "$now" ]]; then
      last=$start
    fi
  fi
  printf '%s\n' "$now" > "${LAST_CHECK_FILE}.partial"
  mv -f "${LAST_CHECK_FILE}.partial" "$LAST_CHECK_FILE"
  count=$(journalctl -u "$RELAY_SERVICE" --since "@$last" --until "@$now" --no-pager 2>/dev/null \
    | grep -Eic 'Non-monotonic DTS|non monotonically increasing dts|Invalid timestamps stream=1|timestamp discontinuity.*stream id=|Timestamps are unset.*stream 1|Queue input is backward in time' || true)
  printf '%s' "$count"
}

run_source_audio_check() {
  local output rc warnings
  [[ -x "$AUDIO_HEALTH_BIN" ]] || return 0
  set +e
  output=$("$AUDIO_HEALTH_BIN" --capture-seconds "$CAPTURE_SECONDS" 2>&1)
  rc=$?
  set -e
  if (( rc == 0 )); then
    return 0
  fi
  warnings=$(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)
  # Source problems are shared-program evidence, not proof of a YouTube-only
  # relay fault. Record them, but never restart the master or Rumble here.
  printf 'epoch=%s reason=SOURCE_AUDIO_WARNING detail=%q\n' "$(date +%s)" "$warnings" > "$WARNING_FILE"
  log "YouTube-bound source audio warning (no shared-stream restart): $warnings"
  return 0
}

main() {
  local relay_pid ts_errors socket_failures=0

  if [[ ! -r "$ENV_FILE" ]]; then
    write_status SKIP ENV_FILE_MISSING no
    return 0
  fi
  if grep -q '^YOUTUBE_STREAM_KEY=REPLACE_WITH_YOUTUBE_STREAM_KEY$' "$ENV_FILE"; then
    write_status SKIP YOUTUBE_KEY_PLACEHOLDER no
    return 0
  fi

  if ! systemctl is-active --quiet "$MASTER_SERVICE"; then
    # The master health system owns master recovery. This watchdog never does.
    write_status SKIP MASTER_NOT_ACTIVE no
    return 0
  fi

  if ! systemctl is-active --quiet "$RELAY_SERVICE"; then
    attempt_repair RELAY_NOT_ACTIVE || true
    return 0
  fi

  relay_pid=$(pid_of "$RELAY_SERVICE")
  if ! canonical_relay_process "$relay_pid"; then
    attempt_repair NONCANONICAL_RELAY_PROCESS || true
    return 0
  fi

  ts_errors=$(recent_timestamp_errors)
  if [[ "$ts_errors" =~ ^[0-9]+$ ]] && (( ts_errors > 0 )); then
    attempt_repair "AUDIO_TIMESTAMP_ERRORS_${ts_errors}" || true
    return 0
  fi

  if ! rtmps_socket_ok "$relay_pid"; then
    if [[ -s "$SOCKET_FAILURE_FILE" ]]; then
      socket_failures=$(cat "$SOCKET_FAILURE_FILE" 2>/dev/null || printf '0')
    fi
    [[ "$socket_failures" =~ ^[0-9]+$ ]] || socket_failures=0
    socket_failures=$((socket_failures + 1))
    printf '%s\n' "$socket_failures" > "$SOCKET_FAILURE_FILE"
    if (( socket_failures >= SOCKET_FAILURES_BEFORE_RESTART )); then
      attempt_repair "RTMPS_SOCKET_MISSING_${socket_failures}_CHECKS" || true
      return 0
    fi
    printf 'epoch=%s reason=RTMPS_SOCKET_MISSING strikes=%s\n' "$(date +%s)" "$socket_failures" > "$WARNING_FILE"
    write_status WARN RTMPS_SOCKET_MISSING no
    return 0
  fi

  rm -f "$SOCKET_FAILURE_FILE"
  run_source_audio_check
  # Preserve a source warning if one was just recorded; otherwise clear stale
  # relay warnings now that the transport path is healthy.
  if [[ -s "$WARNING_FILE" ]] && grep -q 'reason=SOURCE_AUDIO_WARNING' "$WARNING_FILE"; then
    write_status WARN SOURCE_AUDIO_WARNING no
  else
    rm -f "$WARNING_FILE"
    write_status OK HEALTHY no
  fi
}

main "$@"

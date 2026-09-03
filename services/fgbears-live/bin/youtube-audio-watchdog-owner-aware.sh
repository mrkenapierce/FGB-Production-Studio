#!/usr/bin/env bash
set -Eeuo pipefail

# FGBears YouTube owner-aware audio/transport watchdog.
#
# The Lovable exact-question-box compositor is the only permitted YouTube owner.
# Persistent YouTube-side faults may restart that compositor only. This watchdog
# must never restart/stop the shared master or Rumble and must never fail over to
# the legacy direct YouTube relay, because that relay bypasses trivia concealment.

COMP_SERVICE=${FGB_YOUTUBE_COMP_SERVICE:-fgbears-youtube-lovable-compositor.service}
ROUTING_SERVICE=${FGB_YOUTUBE_ROUTING_SERVICE:-fgbears-youtube-lovable-routing.service}
RELAY_SERVICE=${FGB_YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
MASTER_SERVICE=${FGB_MASTER_SERVICE:-fgbears-live.service}
RUMBLE_SERVICE=${FGB_RUMBLE_SERVICE:-fgbears-rumble-relay.service}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
STATE_DIR=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATE_DIR:-/srv/fgbears-live/health/youtube-audio}
STATUS_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATUS_FILE:-$STATE_DIR/status.env}
WARNING_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_WARNING_FILE:-$STATE_DIR/warning.env}
COMP_FAILURE_FILE=${FGB_YOUTUBE_COMP_FAILURE_FILE:-$STATE_DIR/compositor-health-failures}
LAST_DEEP_AUDIO_CHECK_FILE=${FGB_YOUTUBE_DEEP_AUDIO_EPOCH_FILE:-$STATE_DIR/deep-audio-epoch}
CAPTURE_SECONDS=${FGB_YOUTUBE_AUDIO_WATCHDOG_CAPTURE_SECONDS:-8}
DEEP_AUDIO_INTERVAL_SECONDS=${FGB_YOUTUBE_DEEP_AUDIO_INTERVAL_SECONDS:-900}
COMP_FAILURES_BEFORE_RESTART=${FGB_YOUTUBE_COMP_FAILURES_BEFORE_RESTART:-2}
MONITOR_DIR=${FGB_YOUTUBE_MONITOR_DIR:-/run/fgbears-youtube-lovable-compositor}
TRANSPORT_LOOKBACK=${FGB_YOUTUBE_TRANSPORT_LOOKBACK:-75 seconds ago}
TRANSPORT_FAULT_LIMIT=${FGB_YOUTUBE_TRANSPORT_FAULT_LIMIT:-3}

mkdir -p "$STATE_DIR"

log() {
  logger -t fgbears-youtube-audio-watchdog -- "$*"
  printf '%s\n' "$*" >&2
}

pid_of() {
  systemctl show -p MainPID --value "$1" 2>/dev/null || printf '0'
}

active() {
  systemctl is-active --quiet "$1"
}

cmdline_of() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ && -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' ' ' < "/proc/$pid/cmdline"
}

rtmps_socket_ok() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null \
    | grep -F "pid=$pid" \
    | grep -Eq ':[4]43([[:space:]]|$)'
}

exact_box_health_ok() {
  curl -fsS --max-time 3 http://127.0.0.1:8791/healthz 2>/dev/null \
    | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True
assert p.get("sourceCanvas")==[1280,720]
assert p.get("canvas")==[640,360]
assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("maskRegion")=={"x":231,"y":52,"width":399,"height":235}
assert p.get("frameSize")==[399,235]
assert p.get("executionScaling")=="proportional_downstream"
assert p.get("fps")==30
assert p.get("creativeKey")=="yt_rumble_trivia_redirect"
assert p.get("routingAuthority")=="lovable_public_stream_routing"
assert p.get("failClosedDuringQuestion") is True
' >/dev/null 2>&1
}

canonical_compositor_process() {
  local pid=$1 args
  args=$(cmdline_of "$pid") || return 1
  [[ "$args" == *"ffmpeg"* ]] || return 1
  [[ "$args" == *"udp://127.0.0.1:1939?fifo_size=1000000&overrun_nonfatal=1&reuse=1"* ]] || return 1
  [[ "$args" == *" -thread_queue_size 512 "* ]] || return 1
  [[ "$args" == *" -thread_queue_size 32 -f rawvideo "* ]] || return 1
  [[ "$args" == *"scale=640:360:flags=fast_bilinear"* ]] || return 1
  [[ "$args" == *"overlay=231:52:format=auto:shortest=1"* ]] || return 1
  [[ "$args" == *" -c:v libx264 "* ]] || return 1
  [[ "$args" == *" -b:v 2200k "* ]] || return 1
  [[ "$args" == *" -maxrate 2500k "* ]] || return 1
  [[ "$args" == *" -bufsize 4400k "* ]] || return 1
  [[ "$args" == *" -c:a aac "* ]] || return 1
  [[ "$args" == *" -profile:a aac_low "* ]] || return 1
  [[ "$args" == *" -b:a 128k "* ]] || return 1
  [[ "$args" == *" -ar 48000 "* ]] || return 1
  [[ "$args" == *" -ac 2 "* ]] || return 1
  [[ "$args" == *"aresample=48000:async=1:first_pts=0"* ]] || return 1
  [[ "$args" == *"attempt_recovery=1:recover_any_error=1:recovery_wait_time=1:drop_pkts_on_overflow=1:restart_with_keyframe=1"* ]] || return 1
  [[ "$args" == *"rtmps://a.rtmps.youtube.com/"* ]] || return 1
  return 0
}

latest_monitor_segment() {
  find "$MONITOR_DIR" -maxdepth 1 -type f -name 'monitor-*.ts' -size +0c -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | sed -n '1{s/^[^ ]* //;p;q;}'
}

output_audio_format_status() {
  local seg probe
  seg=$(latest_monitor_segment)
  [[ -n "$seg" && -s "$seg" ]] || { printf 'unavailable'; return 0; }
  probe=$(ffprobe -v fatal -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels \
    -of json "$seg" 2>/dev/null) || { printf 'unavailable'; return 0; }
  if printf '%s' "$probe" | python3 -c '
import json,sys
p=json.load(sys.stdin)
s=(p.get("streams") or [{}])[0]
assert s.get("codec_name")=="aac"
assert str(s.get("sample_rate"))=="48000"
assert int(s.get("channels") or 0)==2
' >/dev/null 2>&1; then
    printf 'ok'
  else
    printf 'invalid'
  fi
}

transport_fault_count() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo 999; return 0; }
  journalctl _PID="$pid" --since "$TRANSPORT_LOOKBACK" --no-pager 2>/dev/null \
    | grep -Eci 'Circular buffer overrun|timestamp discontinuity|Packet corrupt|Non-monotonous DTS|Invalid DTS|Queue input is backward in time' \
    || true
}

compositor_core_healthy() {
  local pid faults
  active "$ROUTING_SERVICE" || return 1
  active "$COMP_SERVICE" || return 1
  exact_box_health_ok || return 1
  pid=$(pid_of "$COMP_SERVICE")
  canonical_compositor_process "$pid" || return 1
  rtmps_socket_ok "$pid" || return 1
  faults=$(transport_fault_count "$pid")
  [[ "$faults" =~ ^[0-9]+$ ]] || return 1
  (( faults < TRANSPORT_FAULT_LIMIT )) || return 1
  return 0
}

write_status() {
  local state=$1 reason=$2 repaired=${3:-no} now temporary owner owner_pid faults=0 audio_probe
  now=$(date +%s)
  if active "$COMP_SERVICE"; then
    owner=exact_box_compositor
    owner_pid=$(pid_of "$COMP_SERVICE")
    faults=$(transport_fault_count "$owner_pid")
  else
    owner=none
    owner_pid=0
  fi
  audio_probe=$(output_audio_format_status)
  temporary="${STATUS_FILE}.partial"
  {
    printf 'checked_epoch=%s\n' "$now"
    printf 'state=%s\n' "$state"
    printf 'reason=%s\n' "$reason"
    printf 'owner=%s\n' "$owner"
    printf 'repaired=%s\n' "$repaired"
    printf 'youtube_pid=%s\n' "$owner_pid"
    printf 'compositor_pid=%s\n' "$(pid_of "$COMP_SERVICE")"
    printf 'relay_pid=%s\n' "$(pid_of "$RELAY_SERVICE")"
    printf 'master_pid=%s\n' "$(pid_of "$MASTER_SERVICE")"
    printf 'rumble_pid=%s\n' "$(pid_of "$RUMBLE_SERVICE")"
    printf 'youtube_audio_rate=48000\n'
    printf 'youtube_audio_channels=2\n'
    printf 'output_audio_probe=%s\n' "$audio_probe"
    printf 'recent_transport_faults=%s\n' "$faults"
    printf 'legacy_fallback_allowed=no\n'
  } > "$temporary"
  mv -f "$temporary" "$STATUS_FILE"
}

deep_audio_check_due() {
  local now last=0
  now=$(date +%s)
  if [[ -s "$LAST_DEEP_AUDIO_CHECK_FILE" ]]; then
    last=$(cat "$LAST_DEEP_AUDIO_CHECK_FILE" 2>/dev/null || printf '0')
  fi
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  (( now - last >= DEEP_AUDIO_INTERVAL_SECONDS ))
}

run_source_audio_check() {
  local output rc warnings now
  [[ -x "$AUDIO_HEALTH_BIN" ]] || return 0
  now=$(date +%s)
  printf '%s\n' "$now" > "${LAST_DEEP_AUDIO_CHECK_FILE}.partial"
  mv -f "${LAST_DEEP_AUDIO_CHECK_FILE}.partial" "$LAST_DEEP_AUDIO_CHECK_FILE"
  set +e
  output=$("$AUDIO_HEALTH_BIN" --capture-seconds "$CAPTURE_SECONDS" 2>&1)
  rc=$?
  set -e
  if (( rc == 0 )); then
    rm -f "$WARNING_FILE"
    return 0
  fi
  warnings=$(printf '%s\n' "$output" | grep -E '^(AUDIO_WARNINGS|REASON)=' | tr '\n' ' ' || true)
  printf 'epoch=%s reason=SOURCE_AUDIO_WARNING detail=%q\n' "$now" "$warnings" > "$WARNING_FILE"
  log "YouTube-bound source audio warning; no shared-stream restart: $warnings"
  return 1
}

stop_compositor_fast() {
  active "$COMP_SERVICE" || return 0
  systemctl kill --kill-who=all --signal=SIGINT "$COMP_SERVICE" 2>/dev/null || true
  for _ in {1..6}; do
    active "$COMP_SERVICE" || return 0
    sleep 0.5
  done
  systemctl kill --kill-who=all --signal=SIGKILL "$COMP_SERVICE" 2>/dev/null || true
  for _ in {1..6}; do
    active "$COMP_SERVICE" || return 0
    sleep 0.5
  done
  systemctl stop "$COMP_SERVICE" 2>/dev/null || true
}

restart_compositor_only() {
  log "Persistent YouTube compositor fault; restarting compositor only. Master and Rumble are untouched."
  stop_compositor_fast
  systemctl reset-failed "$COMP_SERVICE" >/dev/null 2>&1 || true
  systemctl start "$COMP_SERVICE" || true
  for _ in {1..15}; do
    if compositor_core_healthy; then
      rm -f "$COMP_FAILURE_FILE"
      write_status OK COMPOSITOR_RESTART_RECOVERED yes
      return 0
    fi
    sleep 1
  done
  write_status FAIL COMPOSITOR_RESTART_DID_NOT_RECOVER yes
  return 1
}

main() {
  local failures=0 pid faults audio_probe

  # The master health system owns master recovery. This watchdog never does.
  if ! active "$MASTER_SERVICE"; then
    write_status SKIP MASTER_NOT_ACTIVE no
    return 0
  fi

  # The legacy direct relay is not an eligible owner. Remove it if anything
  # accidentally re-enables it, while leaving master and Rumble untouched.
  if active "$RELAY_SERVICE"; then
    log "Legacy YouTube relay detected; stopping it to preserve trivia concealment ownership."
    systemctl stop "$RELAY_SERVICE" 2>/dev/null || true
  fi
  systemctl disable "$RELAY_SERVICE" >/dev/null 2>&1 || true
  systemctl enable "$COMP_SERVICE" >/dev/null 2>&1 || true

  if compositor_core_healthy; then
    rm -f "$COMP_FAILURE_FILE"
    audio_probe=$(output_audio_format_status)
    if [[ "$audio_probe" == invalid ]]; then
      write_status WARN OUTPUT_AUDIO_CONTRACT_WARNING no
      return 0
    fi
    if deep_audio_check_due; then
      if run_source_audio_check; then
        write_status OK EXACT_BOX_HEALTHY no
      else
        write_status WARN SOURCE_AUDIO_WARNING no
      fi
    elif [[ -s "$WARNING_FILE" ]] && grep -q 'reason=SOURCE_AUDIO_WARNING' "$WARNING_FILE"; then
      write_status WARN SOURCE_AUDIO_WARNING no
    else
      rm -f "$WARNING_FILE"
      write_status OK EXACT_BOX_HEALTHY no
    fi
    return 0
  fi

  if active "$COMP_SERVICE"; then
    pid=$(pid_of "$COMP_SERVICE")
    faults=$(transport_fault_count "$pid")
    if [[ -s "$COMP_FAILURE_FILE" ]]; then
      failures=$(cat "$COMP_FAILURE_FILE" 2>/dev/null || printf '0')
    fi
    [[ "$failures" =~ ^[0-9]+$ ]] || failures=0
    failures=$((failures + 1))
    printf '%s\n' "$failures" > "$COMP_FAILURE_FILE"
    if (( failures < COMP_FAILURES_BEFORE_RESTART )); then
      write_status WARN "COMPOSITOR_HEALTH_TRANSIENT_faults_${faults}" no
      return 0
    fi
    restart_compositor_only
    return $?
  fi

  # If the sole permitted owner is down, bring back only that owner.
  rm -f "$COMP_FAILURE_FILE"
  restart_compositor_only
}

main "$@"

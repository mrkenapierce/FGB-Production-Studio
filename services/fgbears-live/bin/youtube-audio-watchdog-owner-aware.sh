#!/usr/bin/env bash
set -Eeuo pipefail

# FGBears YouTube owner-aware audio/transport watchdog.
#
# Primary owner: Lovable-controlled exact-question-box compositor.
# Fallback owner: legacy H.264-copy / transparent AAC clock-repair relay.
#
# The source program is already mastered. This watchdog checks signal integrity,
# timestamp/transport continuity and YouTube output format; it never applies or
# requests a second mastering pass. It never restarts or stops the shared master
# or Rumble.

COMP_SERVICE=${FGB_YOUTUBE_COMP_SERVICE:-fgbears-youtube-lovable-compositor.service}
ROUTING_SERVICE=${FGB_YOUTUBE_ROUTING_SERVICE:-fgbears-youtube-lovable-routing.service}
RELAY_SERVICE=${FGB_YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
MASTER_SERVICE=${FGB_MASTER_SERVICE:-fgbears-live.service}
RUMBLE_SERVICE=${FGB_RUMBLE_SERVICE:-fgbears-rumble-relay.service}
LEGACY_WATCHDOG=${FGB_YOUTUBE_LEGACY_WATCHDOG:-/usr/local/libexec/fgbears-youtube-audio-watchdog-legacy}
AUDIO_HEALTH_BIN=${FGB_AUDIO_HEALTH_BIN:-/usr/local/bin/fgbears-audio-health}
STATE_DIR=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATE_DIR:-/srv/fgbears-live/health/youtube-audio}
STATUS_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATUS_FILE:-$STATE_DIR/status.env}
WARNING_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_WARNING_FILE:-$STATE_DIR/warning.env}
COMP_SOCKET_FAILURE_FILE=${FGB_YOUTUBE_COMP_SOCKET_FAILURE_FILE:-$STATE_DIR/compositor-socket-failures}
LAST_DEEP_AUDIO_CHECK_FILE=${FGB_YOUTUBE_DEEP_AUDIO_EPOCH_FILE:-$STATE_DIR/deep-audio-epoch}
CAPTURE_SECONDS=${FGB_YOUTUBE_AUDIO_WATCHDOG_CAPTURE_SECONDS:-8}
DEEP_AUDIO_INTERVAL_SECONDS=${FGB_YOUTUBE_DEEP_AUDIO_INTERVAL_SECONDS:-900}
COMP_SOCKET_FAILURES_BEFORE_FALLBACK=${FGB_YOUTUBE_COMP_SOCKET_FAILURES_BEFORE_FALLBACK:-2}
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

latest_completed_monitor_segment() {
  find "$MONITOR_DIR" -maxdepth 1 -type f -name 'monitor-*.ts' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | sed -n '2{s/^[^ ]* //;p;q;}'
}

output_audio_format_ok() {
  local seg probe
  seg=$(latest_completed_monitor_segment)
  [[ -n "$seg" && -s "$seg" ]] || return 1
  probe=$(ffprobe -v fatal -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels \
    -of json "$seg" 2>/dev/null) || return 1
  printf '%s' "$probe" | python3 -c '
import json,sys
p=json.load(sys.stdin)
s=(p.get("streams") or [{}])[0]
assert s.get("codec_name")=="aac"
assert str(s.get("sample_rate"))=="48000"
assert int(s.get("channels") or 0)==2
' >/dev/null 2>&1
}

transport_fault_count() {
  local pid=$1
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo 999; return 0; }
  journalctl _PID="$pid" --since "$TRANSPORT_LOOKBACK" --no-pager 2>/dev/null \
    | grep -Eci 'Circular buffer overrun|timestamp discontinuity|Packet corrupt|Non-monotonous DTS|Invalid DTS|Queue input is backward in time' \
    || true
}

compositor_healthy() {
  local pid faults
  active "$ROUTING_SERVICE" || return 1
  active "$COMP_SERVICE" || return 1
  exact_box_health_ok || return 1
  pid=$(pid_of "$COMP_SERVICE")
  canonical_compositor_process "$pid" || return 1
  rtmps_socket_ok "$pid" || return 1
  output_audio_format_ok || return 1
  faults=$(transport_fault_count "$pid")
  [[ "$faults" =~ ^[0-9]+$ ]] || return 1
  (( faults < TRANSPORT_FAULT_LIMIT )) || return 1
  return 0
}

write_status() {
  local state=$1 reason=$2 owner=$3 repaired=${4:-no} now temporary owner_service owner_pid faults=0
  now=$(date +%s)
  owner_service=$([[ "$owner" == exact_box_compositor ]] && printf '%s' "$COMP_SERVICE" || printf '%s' "$RELAY_SERVICE")
  owner_pid=$(pid_of "$owner_service")
  if [[ "$owner" == exact_box_compositor ]]; then faults=$(transport_fault_count "$owner_pid"); fi
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
    printf 'recent_transport_faults=%s\n' "$faults"
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

fallback_to_legacy() {
  local reason=$1
  log "Exact-box YouTube owner unhealthy; falling back to legacy relay; reason=$reason"
  stop_compositor_fast
  systemctl disable "$COMP_SERVICE" >/dev/null 2>&1 || true
  systemctl unmask "$RELAY_SERVICE" >/dev/null 2>&1 || true
  systemctl enable "$RELAY_SERVICE" >/dev/null 2>&1 || true
  rm -f "$COMP_SOCKET_FAILURE_FILE"
  [[ -x "$LEGACY_WATCHDOG" ]] || {
    write_status FAIL LEGACY_WATCHDOG_MISSING none no
    return 1
  }
  exec "$LEGACY_WATCHDOG"
}

main() {
  local failures=0 pid faults

  # The master health system owns master recovery. This watchdog never does.
  if ! active "$MASTER_SERVICE"; then
    write_status SKIP MASTER_NOT_ACTIVE none no
    return 0
  fi

  if compositor_healthy; then
    rm -f "$COMP_SOCKET_FAILURE_FILE"
    if active "$RELAY_SERVICE"; then
      log "Duplicate YouTube fallback relay detected while exact-box compositor is healthy; stopping fallback relay."
      systemctl stop "$RELAY_SERVICE" 2>/dev/null || true
    fi
    systemctl disable "$RELAY_SERVICE" >/dev/null 2>&1 || true
    systemctl enable "$COMP_SERVICE" >/dev/null 2>&1 || true

    if deep_audio_check_due; then
      if run_source_audio_check; then
        write_status OK EXACT_BOX_HEALTHY exact_box_compositor no
      else
        write_status WARN SOURCE_AUDIO_WARNING exact_box_compositor no
      fi
    elif [[ -s "$WARNING_FILE" ]] && grep -q 'reason=SOURCE_AUDIO_WARNING' "$WARNING_FILE"; then
      write_status WARN SOURCE_AUDIO_WARNING exact_box_compositor no
    else
      rm -f "$WARNING_FILE"
      write_status OK EXACT_BOX_HEALTHY exact_box_compositor no
    fi
    return 0
  fi

  # A running compositor gets two consecutive watchdog opportunities before
  # fallback. This tolerates one transient handshake/segment rotation but does
  # not allow repeated buffer overruns or timestamp discontinuities to remain
  # invisible while the RTMP socket is technically still connected.
  if active "$COMP_SERVICE"; then
    pid=$(pid_of "$COMP_SERVICE")
    faults=$(transport_fault_count "$pid")
    if [[ -s "$COMP_SOCKET_FAILURE_FILE" ]]; then
      failures=$(cat "$COMP_SOCKET_FAILURE_FILE" 2>/dev/null || printf '0')
    fi
    [[ "$failures" =~ ^[0-9]+$ ]] || failures=0
    failures=$((failures + 1))
    printf '%s\n' "$failures" > "$COMP_SOCKET_FAILURE_FILE"
    if (( failures < COMP_SOCKET_FAILURES_BEFORE_FALLBACK )); then
      write_status WARN "COMPOSITOR_HEALTH_TRANSIENT_faults_${faults}" exact_box_compositor no
      return 0
    fi
    fallback_to_legacy "COMPOSITOR_HEALTH_FAILED_${failures}_CHECKS_faults_${faults}"
    return 0
  fi

  fallback_to_legacy COMPOSITOR_NOT_ACTIVE
}

main "$@"

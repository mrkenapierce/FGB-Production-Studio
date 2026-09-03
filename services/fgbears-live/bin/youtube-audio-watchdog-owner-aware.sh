#!/usr/bin/env bash
set -Eeuo pipefail

COMP_SERVICE=${FGB_YOUTUBE_COMP_SERVICE:-fgbears-youtube-lovable-compositor.service}
ROUTING_SERVICE=${FGB_YOUTUBE_ROUTING_SERVICE:-fgbears-youtube-lovable-routing.service}
RELAY_SERVICE=${FGB_YOUTUBE_RELAY_SERVICE:-fgbears-youtube-relay.service}
MASTER_SERVICE=${FGB_MASTER_SERVICE:-fgbears-live.service}
RUMBLE_SERVICE=${FGB_RUMBLE_SERVICE:-fgbears-rumble-relay.service}
STATE_DIR=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATE_DIR:-/srv/fgbears-live/health/youtube-audio}
STATUS_FILE=${FGB_YOUTUBE_AUDIO_WATCHDOG_STATUS_FILE:-$STATE_DIR/status.env}
COMP_FAILURE_FILE=${FGB_YOUTUBE_COMP_FAILURE_FILE:-$STATE_DIR/compositor-health-failures}
MONITOR_DIR=${FGB_YOUTUBE_MONITOR_DIR:-/run/fgbears-youtube-lovable-compositor}
TRANSPORT_LOOKBACK=${FGB_YOUTUBE_TRANSPORT_LOOKBACK:-75 seconds ago}
TRANSPORT_FAULT_LIMIT=${FGB_YOUTUBE_TRANSPORT_FAULT_LIMIT:-3}
COMP_FAILURES_BEFORE_RESTART=${FGB_YOUTUBE_COMP_FAILURES_BEFORE_RESTART:-2}
mkdir -p "$STATE_DIR"

pid_of(){ systemctl show -p MainPID --value "$1" 2>/dev/null || printf '0'; }
active(){ systemctl is-active --quiet "$1"; }
rtmps_socket_ok(){ local p=$1; [[ "$p" =~ ^[1-9][0-9]*$ ]] && ss -ntpH state established 2>/dev/null | grep -F "pid=$p" | grep -Eq ':[4]43([[:space:]]|$)'; }

exact_box_health_ok(){
  curl -fsS --max-time 3 http://127.0.0.1:8791/healthz 2>/dev/null | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True
assert p.get("sourceCanvas")==[1280,720]
assert p.get("canvas")==[1280,720]
assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("maskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("frameSize")==[798,470]
assert p.get("fps")==30
assert p.get("creativeKey")=="yt_rumble_trivia_redirect"
assert p.get("failClosedDuringQuestion") is True
' >/dev/null 2>&1
}

latest_monitor_segment(){ find "$MONITOR_DIR" -maxdepth 1 -type f -name 'monitor-*.ts' -size +0c -printf '%T@ %p\n' 2>/dev/null | sort -nr | sed -n '1{s/^[^ ]* //;p;q;}'; }
output_av_ok(){
  local seg; seg=$(latest_monitor_segment); [[ -n "$seg" && -s "$seg" ]] || return 1
  ffprobe -v fatal -show_entries stream=codec_type,codec_name,sample_rate,channels,width,height,r_frame_rate -of json "$seg" | python3 -c '
import json,sys
p=json.load(sys.stdin); s=p.get("streams",[])
a=next(x for x in s if x.get("codec_type")=="audio"); v=next(x for x in s if x.get("codec_type")=="video")
assert a.get("codec_name")=="aac" and str(a.get("sample_rate"))=="48000" and int(a.get("channels") or 0)==2
assert (int(v.get("width",0)),int(v.get("height",0)))==(1280,720)
assert v.get("r_frame_rate") in {"30/1","60/2"}
' >/dev/null 2>&1
}
transport_fault_count(){ local p=$1; journalctl _PID="$p" --since "$TRANSPORT_LOOKBACK" --no-pager 2>/dev/null | grep -Eci 'Circular buffer overrun|timestamp discontinuity|Packet corrupt|Non-monotonous DTS|Invalid DTS|Queue input is backward in time' || true; }

compositor_core_healthy(){
  active "$ROUTING_SERVICE" || return 1
  active "$COMP_SERVICE" || return 1
  exact_box_health_ok || return 1
  local p faults; p=$(pid_of "$COMP_SERVICE"); rtmps_socket_ok "$p" || return 1
  faults=$(transport_fault_count "$p"); [[ "$faults" =~ ^[0-9]+$ ]] || return 1
  (( faults < TRANSPORT_FAULT_LIMIT )) || return 1
  return 0
}

write_status(){
  local state=$1 reason=$2 now p faults probe
  now=$(date +%s); p=$(pid_of "$COMP_SERVICE"); faults=0
  [[ "$p" =~ ^[1-9][0-9]*$ ]] && faults=$(transport_fault_count "$p") || true
  probe=invalid; output_av_ok && probe=ok || true
  cat >"${STATUS_FILE}.partial" <<EOF
checked_epoch=$now
state=$state
reason=$reason
owner=exact_box_compositor
youtube_pid=$p
compositor_pid=$p
relay_pid=$(pid_of "$RELAY_SERVICE")
master_pid=$(pid_of "$MASTER_SERVICE")
rumble_pid=$(pid_of "$RUMBLE_SERVICE")
youtube_audio_rate=48000
youtube_audio_channels=2
output_av_probe=$probe
recent_transport_faults=$faults
legacy_fallback_allowed=no
EOF
  mv -f "${STATUS_FILE}.partial" "$STATUS_FILE"
}

restart_compositor_only(){
  systemctl kill --kill-who=all --signal=SIGINT "$COMP_SERVICE" 2>/dev/null || true
  sleep 2
  systemctl reset-failed "$COMP_SERVICE" >/dev/null 2>&1 || true
  systemctl start "$COMP_SERVICE" || true
  for _ in {1..20}; do compositor_core_healthy && { rm -f "$COMP_FAILURE_FILE"; write_status OK COMPOSITOR_RESTART_RECOVERED; return 0; }; sleep 1; done
  write_status FAIL COMPOSITOR_RESTART_DID_NOT_RECOVER; return 1
}

main(){
  active "$MASTER_SERVICE" || { write_status SKIP MASTER_NOT_ACTIVE; return 0; }
  active "$RELAY_SERVICE" && systemctl stop "$RELAY_SERVICE" 2>/dev/null || true
  systemctl disable "$RELAY_SERVICE" >/dev/null 2>&1 || true
  if compositor_core_healthy; then rm -f "$COMP_FAILURE_FILE"; write_status OK NATIVE_720P_HEALTHY; return 0; fi
  local f=0; [[ -s "$COMP_FAILURE_FILE" ]] && f=$(cat "$COMP_FAILURE_FILE" 2>/dev/null || echo 0); [[ "$f" =~ ^[0-9]+$ ]] || f=0; f=$((f+1)); echo "$f" > "$COMP_FAILURE_FILE"
  (( f < COMP_FAILURES_BEFORE_RESTART )) && { write_status WARN COMPOSITOR_HEALTH_TRANSIENT; return 0; }
  restart_compositor_only
}
main "$@"

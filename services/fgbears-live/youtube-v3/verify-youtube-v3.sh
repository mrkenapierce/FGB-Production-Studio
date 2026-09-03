#!/usr/bin/env bash
set -Eeuo pipefail

MODE=final
if [[ "${1:-}" == "--transport-only" ]]; then MODE=transport; shift; fi
[[ $# -eq 0 ]] || { echo "Usage: $0 [--transport-only]" >&2; exit 64; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
YOUTUBE=fgbears-youtube-v3.service
STATE=/run/fgbears-youtube-v3/overlay-state.json
PROGRESS=/run/fgbears-youtube-v3/ffmpeg-progress.log
ACTIVE_DIR=/opt/fgbears-live/youtube-v3
V2_QUAR=/opt/fgbears-live/quarantine/youtube-v2-retired-20260903
GENERATION_FILE=/etc/fgbears-live/youtube-generation
HEALTHCHECK=/usr/local/bin/fgbears-healthcheck
RETIRED=(
  fgbears-youtube-v2.service
  fgbears-youtube-output.service
  fgbears-youtube-relay.service
  fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service
  fgbears-youtube-lovable-compositor.service
  fgbears-youtube-audio-watchdog.service
  fgbears-youtube-audio-watchdog.timer
)

pid(){ systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
restarts(){ systemctl show -p NRestarts --value "$1" 2>/dev/null || echo 0; }
connected(){
  local p=$1 port=$2
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v x=":$port" 'index($0,q)&&index($0,x){ok=1} END{exit(ok?0:1)}'
}
fail(){ echo "YOUTUBE_V3_VERIFY=FAIL mode=$MODE reason=$1" >&2; exit 1; }

systemctl is-active --quiet "$MASTER" || fail master_inactive
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive
systemctl is-active --quiet "$YOUTUBE" || fail youtube_v3_inactive

M=$(pid "$MASTER"); R=$(pid "$RUMBLE"); Y=$(pid "$YOUTUBE")
[[ "$M" =~ ^[1-9][0-9]*$ ]] || fail invalid_master_pid
[[ "$R" =~ ^[1-9][0-9]*$ ]] || fail invalid_rumble_pid
[[ "$Y" =~ ^[1-9][0-9]*$ ]] || fail invalid_youtube_pid
connected "$R" 1935 || fail rumble_socket_missing
connected "$Y" 443 || fail youtube_socket_missing

nice=$(systemctl show -p Nice --value "$YOUTUBE" 2>/dev/null || echo 0)
[[ "$nice" == "0" ]] || fail "youtube_priority_penalty_present:$nice"
[[ -x "$ACTIVE_DIR/youtube-v3-overlay.py" ]] || fail active_overlay_missing
[[ -x "$ACTIVE_DIR/run-youtube-v3.sh" ]] || fail active_runner_missing

[[ -s "$STATE" ]] || fail overlay_state_missing
python3 - "$STATE" <<'PY' || exit 1
import json, sys, time
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p.get('workerVersion') == 'youtube-v3', p.get('workerVersion')
assert p.get('maskRegion') == {
    'x':462,'y':104,'width':798,'height':470,
    'coordinateSpace':'pixels','referenceWidth':1280,'referenceHeight':720,
}, p.get('maskRegion')
assert p.get('frameSize') == [798,470], p.get('frameSize')
assert p.get('presentationMode') == 'full_creative_scaled', p.get('presentationMode')
assert p.get('routingAuthority') == 'lovable_public_stream_routing', p.get('routingAuthority')
assert float(p.get('fps') or 0) == 5.0, p.get('fps')
keys=p.get('availableCreativeKeys')
assert isinstance(keys,list) and 'yt_rumble_trivia_redirect' in keys, keys
last=float(p.get('lastGoodEpoch') or 0)
assert last > 0 and time.time()-last < 10, (last, time.time()-last if last else None)
if p.get('ok') is True:
    requested=p.get('creativeKey')
    assert isinstance(requested,str) and requested in keys, (requested, keys)
    if p.get('active') is True:
        assert p.get('renderedCreativeKey') == requested, p
    else:
        assert p.get('renderedCreativeKey') is None, p
print('OVERLAY_STATE=PASS phase=%s active=%s latency_ms=%s clock_misses=%s' % (
    p.get('phase'), str(bool(p.get('active'))).lower(), p.get('routingLatencyMs'), p.get('frameClockMisses')))
PY

[[ -s "$PROGRESS" ]] || fail youtube_progress_missing
age=$(( $(date +%s) - $(stat -c %Y "$PROGRESS") ))
(( age < 10 )) || fail "youtube_progress_stale:${age}s"
speed=$(sed -n 's/^speed=\([0-9.]*\)x$/\1/p' "$PROGRESS" | tail -n1)
fps=$(sed -n 's/^fps=\([0-9.]*\)$/\1/p' "$PROGRESS" | tail -n1)
drop=$(sed -n 's/^drop_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)
dup=$(sed -n 's/^dup_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)
[[ -n "$speed" ]] || fail youtube_speed_missing
python3 - "$speed" <<'PY' || fail youtube_below_realtime
import sys
assert float(sys.argv[1]) >= 0.98, sys.argv[1]
PY

invocation=$(systemctl show -p InvocationID --value "$YOUTUBE" 2>/dev/null || true)
if [[ -n "$invocation" ]]; then
  journal=$(journalctl _SYSTEMD_INVOCATION_ID="$invocation" --no-pager 2>/dev/null || true)
else
  journal=$(journalctl -u "$YOUTUBE" --since '-5 minutes' --no-pager 2>/dev/null || true)
fi
if grep -Fq 'Circular buffer overrun' <<<"$journal"; then
  fail youtube_udp_circular_buffer_overrun
fi
# The copy/remux normalizer may encounter incomplete packets while joining the
# live UDP stream. The downstream compositor decoder may not.
if grep -Ev '\[v3-ingest\]' <<<"$journal" | grep -Eq 'non-existing PPS|decode_slice_header error|no frame!'; then
  fail downstream_decoder_not_synchronized
fi

if [[ "$MODE" == final ]]; then
  for unit in "${RETIRED[@]}"; do
    systemctl is-active --quiet "$unit" && fail "retired_unit_active:$unit"
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    [[ "$state" == masked* ]] || fail "retired_unit_not_masked:$unit:$state"
  done
  [[ -d "$V2_QUAR" ]] || fail v2_quarantine_missing
  if find "$V2_QUAR" -type f -perm /111 -print -quit 2>/dev/null | grep -q .; then
    fail v2_quarantine_contains_executable
  fi
  [[ ! -e /opt/fgbears-live/youtube-v2 ]] || fail v2_active_runtime_present
  [[ -r "$GENERATION_FILE" ]] || fail generation_marker_missing
  [[ "$(cat "$GENERATION_FILE")" == v3 ]] || fail generation_marker_not_v3
  [[ -x "$HEALTHCHECK" ]] || fail healthcheck_missing
  grep -Fq 'recover_youtube_destination' "$HEALTHCHECK" || fail healthcheck_not_generation_aware
  grep -Fq 'YOUTUBE_GENERATION_FILE=' "$HEALTHCHECK" || fail healthcheck_generation_marker_missing
  grep -Fq 'YOUTUBE_CUTOVER_MARKER=' "$HEALTHCHECK" || fail healthcheck_cutover_guard_missing
fi

pressure=$(awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){split($i,a,"="); print a[2]}}' /proc/pressure/cpu 2>/dev/null || true)
printf 'YOUTUBE_V3_VERIFY=PASS mode=%s master=%s rumble=%s youtube=%s youtube_restarts=%s speed=%sx fps=%s drop=%s dup=%s cpu_pressure_avg10=%s rumble_1935=yes youtube_443=yes v2=%s\n' \
  "$MODE" "$M" "$R" "$Y" "$(restarts "$Y")" "$speed" "${fps:-NA}" "${drop:-NA}" "${dup:-NA}" "${pressure:-NA}" "$([[ "$MODE" == final ]] && echo quarantined || echo rollback_ready)"

#!/usr/bin/env bash
set -Eeuo pipefail

MODE=final
if [[ "${1:-}" == "--transport-only" ]]; then MODE=transport; shift; fi
[[ $# -eq 0 ]] || { echo "Usage: $0 [--transport-only]" >&2; exit 64; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
CACHE=fgbears-lovable-state-cache.service
YOUTUBE=fgbears-youtube-v3.service
CONTROL_STATE=/run/fgbears-control-plane/stream-state.json
CONTROL_HEALTH=/run/fgbears-control-plane/cache-health.json
PROGRESS=/run/fgbears-youtube-v3/ffmpeg-progress.log
ACTIVE_DIR=/opt/fgbears-live/youtube-v3
V2_QUAR=/opt/fgbears-live/quarantine/youtube-v2-retired-20260903
GENERATION_FILE=/etc/fgbears-live/youtube-generation
HEALTHCHECK=/usr/local/bin/fgbears-healthcheck
RETIRED=(
  fgbears-youtube-v2-health.timer fgbears-youtube-v2-health.service
  fgbears-youtube-v2.service fgbears-youtube-output.service
  fgbears-youtube-relay.service fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service
  fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer
  fgbears-youtube-dynamic-card.service
  fgbears-youtube-freeze-card-refresh.service fgbears-youtube-freeze-card-refresh.timer
  fgbears-youtube-v3-source.service fgbears-youtube-v3-supervisor.service
)

pid(){ systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
restarts(){ systemctl show -p NRestarts --value "$1" 2>/dev/null || echo 0; }
connected(){
  local p=$1 port=$2
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v x=":$port" 'index($0,q)&&index($0,x){ok=1} END{exit(ok?0:1)}'
}
fail(){ echo "YOUTUBE_V3_VERIFY=FAIL mode=$MODE reason=$1" >&2; exit 1; }
media_us(){ sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1; }
measure_rate(){
  local m0 m1 t0 t1
  m0=$(media_us); [[ "$m0" =~ ^[0-9]+$ ]] || return 1
  t0=$(date +%s%N); sleep 10
  m1=$(media_us); [[ "$m1" =~ ^[0-9]+$ ]] || return 1
  t1=$(date +%s%N)
  python3 - "$m0" "$m1" "$t0" "$t1" <<'PY'
import sys
m0,m1,t0,t1=map(int,sys.argv[1:]); wall=(t1-t0)/1_000_000_000; media=(m1-m0)/1_000_000
assert wall > 0 and media >= 0
print(f'{media/wall:.4f}')
PY
}

systemctl is-active --quiet "$MASTER" || fail master_inactive
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive
systemctl is-active --quiet "$CACHE" || fail lovable_cache_inactive
systemctl is-active --quiet "$YOUTUBE" || fail youtube_v3_inactive
M=$(pid "$MASTER"); R=$(pid "$RUMBLE"); C=$(pid "$CACHE"); Y=$(pid "$YOUTUBE")
[[ "$M" =~ ^[1-9][0-9]*$ && "$R" =~ ^[1-9][0-9]*$ && "$C" =~ ^[1-9][0-9]*$ && "$Y" =~ ^[1-9][0-9]*$ ]] || fail invalid_core_pid
connected "$R" 1935 || fail rumble_socket_missing
connected "$Y" 443 || fail youtube_socket_missing

[[ -x "$ACTIVE_DIR/youtube-v3-overlay.py" ]] || fail active_overlay_missing
[[ -x "$ACTIVE_DIR/lovable-state-cache.py" ]] || fail control_cache_worker_missing
[[ -x "$ACTIVE_DIR/run-youtube-v3.sh" ]] || fail active_runner_missing
! grep -Eq 'urllib|urlopen|requests|http://|https://' "$ACTIVE_DIR/youtube-v3-overlay.py" || fail renderer_contains_network_io
grep -Fq 'HOLD_SECONDS = float' "$ACTIVE_DIR/youtube-v3-overlay.py" || fail concealment_hold_missing
grep -Fq '"15"' "$ACTIVE_DIR/youtube-v3-overlay.py" || fail concealment_hold_not_15_seconds
grep -Fq 'OUTPUT_REGION' "$ACTIVE_DIR/youtube-v3-overlay.py" || fail scaled_overlay_region_missing
grep -Fq -- '-video_size 399x235' "$ACTIVE_DIR/run-youtube-v3.sh" || fail scaled_overlay_pipe_missing
grep -Fq 'overlay=231:52:' "$ACTIVE_DIR/run-youtube-v3.sh" || fail scaled_overlay_coordinates_missing
grep -Fq 'scale=640:360:flags=fast_bilinear' "$ACTIVE_DIR/run-youtube-v3.sh" || fail youtube_output_not_360p
grep -Fq -- '-threads 1' "$ACTIVE_DIR/run-youtube-v3.sh" || fail youtube_encoder_not_single_threaded
grep -Fq '/api/public/fgbears/stream-routing' "$ACTIVE_DIR/lovable-state-cache.py" || fail cache_not_using_authoritative_contract

[[ -s "$CONTROL_STATE" && -s "$CONTROL_HEALTH" ]] || fail control_state_or_health_missing
python3 - "$CONTROL_STATE" "$CONTROL_HEALTH" <<'PY' || fail control_state_invalid
from datetime import datetime
import json, sys, time
state=json.load(open(sys.argv[1], encoding='utf-8')); health=json.load(open(sys.argv[2], encoding='utf-8'))
assert state.get('schemaVersion') == 'fgb-stream-state/v1'
assert isinstance(state.get('revision'),str) and state['revision']
assert datetime.fromisoformat(str(state.get('validUntil')).replace('Z','+00:00')).timestamp() > time.time()
p=state.get('presentation') or {}; routing=p.get('routing') or {}
assert (routing.get('rumble') or {}).get('rendersRealQuestion') is True
region=(((routing.get('youtube') or {}).get('differenceLayer') or {}).get('region') or (p.get('mask') or {}).get('region'))
assert region == {'x':462,'y':104,'width':798,'height':470,'coordinateSpace':'pixels','referenceWidth':1280,'referenceHeight':720}
diff=((routing.get('youtube') or {}).get('differenceLayer') or {})
if diff.get('enabled') is True:
    assert diff.get('creativeKey') == 'yt_rumble_trivia_redirect'
    trivia=p.get('trivia') or {}
    assert trivia.get('questionVisible') is True
    assert trivia.get('youtubeRedirectRequired') is True
assert health.get('workerVersion') == 'lovable-control-cache-v1'
assert health.get('authority') == '/api/public/fgbears/stream-routing'
assert health.get('ok') is True
last=float(health.get('lastGoodEpoch') or 0); assert last > 0 and time.time()-last < 10
PY

[[ -s "$PROGRESS" ]] || fail youtube_progress_missing
age=$(( $(date +%s) - $(stat -c %Y "$PROGRESS") )); (( age < 10 )) || fail "youtube_progress_stale:${age}s"
rate=$(measure_rate) || fail youtube_rate_measurement_failed
python3 - "$rate" <<'PY' || fail youtube_below_realtime
import sys
assert float(sys.argv[1]) >= 0.98, sys.argv[1]
PY
fps=$(sed -n 's/^fps=\([0-9.]*\)$/\1/p' "$PROGRESS" | tail -n1)
drop=$(sed -n 's/^drop_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)
dup=$(sed -n 's/^dup_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)

if [[ "$MODE" == final ]]; then
  for unit in "${RETIRED[@]}"; do
    systemctl is-active --quiet "$unit" && fail "retired_unit_active:$unit"
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    [[ "$state" == masked* || "$state" == not-found ]] || fail "retired_unit_not_masked:$unit:$state"
  done
  [[ -d "$V2_QUAR" ]] || fail v2_quarantine_missing
  [[ ! -e /opt/fgbears-live/youtube-v2 ]] || fail v2_active_runtime_present
  [[ -r "$GENERATION_FILE" && "$(cat "$GENERATION_FILE")" == v3 ]] || fail generation_marker_not_v3
  [[ -x "$HEALTHCHECK" ]] || fail healthcheck_missing
  grep -Fq 'recover_youtube_destination' "$HEALTHCHECK" || fail healthcheck_not_generation_aware
fi

pressure=$(awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){split($i,a,"="); print a[2]}}' /proc/pressure/cpu 2>/dev/null || true)
printf 'YOUTUBE_V3_VERIFY=PASS mode=%s master=%s rumble=%s cache=%s youtube=%s youtube_restarts=%s sustained_rate=%sx fps=%s drop=%s dup=%s cpu_pressure_avg10=%s hold=15s output=640x360 overlay=399x235@231,52\n' \
  "$MODE" "$M" "$R" "$C" "$Y" "$(restarts "$Y")" "$rate" "${fps:-NA}" "${drop:-NA}" "${dup:-NA}" "${pressure:-NA}"

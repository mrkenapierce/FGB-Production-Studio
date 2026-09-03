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
media_us(){ sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1; }
measure_rate(){
  local m0 m1 t0 t1
  m0=$(media_us); [[ "$m0" =~ ^[0-9]+$ ]] || return 1
  t0=$(date +%s%N)
  sleep 5
  m1=$(media_us); [[ "$m1" =~ ^[0-9]+$ ]] || return 1
  t1=$(date +%s%N)
  python3 - "$m0" "$m1" "$t0" "$t1" <<'PY'
import sys
m0,m1,t0,t1=map(int,sys.argv[1:])
wall=(t1-t0)/1_000_000_000
media=(m1-m0)/1_000_000
assert wall > 0 and media >= 0
print(f'{media/wall:.4f}')
PY
}

systemctl is-active --quiet "$MASTER" || fail master_inactive
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive
systemctl is-active --quiet "$CACHE" || fail lovable_cache_inactive
systemctl is-active --quiet "$YOUTUBE" || fail youtube_v3_inactive

M=$(pid "$MASTER"); R=$(pid "$RUMBLE"); C=$(pid "$CACHE"); Y=$(pid "$YOUTUBE")
[[ "$M" =~ ^[1-9][0-9]*$ ]] || fail invalid_master_pid
[[ "$R" =~ ^[1-9][0-9]*$ ]] || fail invalid_rumble_pid
[[ "$C" =~ ^[1-9][0-9]*$ ]] || fail invalid_cache_pid
[[ "$Y" =~ ^[1-9][0-9]*$ ]] || fail invalid_youtube_pid
connected "$R" 1935 || fail rumble_socket_missing
connected "$Y" 443 || fail youtube_socket_missing

nice=$(systemctl show -p Nice --value "$YOUTUBE" 2>/dev/null || echo 0)
[[ "$nice" == "0" ]] || fail "youtube_priority_penalty_present:$nice"
[[ -x "$ACTIVE_DIR/youtube-v3-overlay.py" ]] || fail active_overlay_missing
[[ -x "$ACTIVE_DIR/lovable-state-cache.py" ]] || fail control_cache_worker_missing
[[ -x "$ACTIVE_DIR/run-youtube-v3.sh" ]] || fail active_runner_missing

# Hard architecture gate: the media-clock renderer may not contain an HTTP client.
if grep -Eq 'urllib|urlopen|requests|http://|https://' "$ACTIVE_DIR/youtube-v3-overlay.py"; then
  fail renderer_contains_network_io
fi
grep -Fq '/api/public/fgbears/stream-routing' "$ACTIVE_DIR/lovable-state-cache.py" || fail cache_not_using_authoritative_contract

[[ -s "$CONTROL_STATE" ]] || fail control_state_missing
[[ -s "$CONTROL_HEALTH" ]] || fail control_health_missing
python3 - "$CONTROL_STATE" "$CONTROL_HEALTH" <<'PY' || fail control_state_invalid
from datetime import datetime
import json, sys, time
state=json.load(open(sys.argv[1], encoding='utf-8'))
health=json.load(open(sys.argv[2], encoding='utf-8'))
assert state.get('schemaVersion') == 'fgb-stream-state/v1', state.get('schemaVersion')
assert isinstance(state.get('revision'),str) and state['revision'], state.get('revision')
expiry=datetime.fromisoformat(str(state.get('validUntil')).replace('Z','+00:00')).timestamp()
assert expiry > time.time(), (state.get('validUntil'), expiry-time.time())
p=state.get('presentation') or {}
for key in ('adBreak','trivia','routing','overlay','crawl','news','schedule'):
    assert isinstance(p.get(key),dict), key
routing=p['routing']; rumble=routing.get('rumble') or {}; youtube=routing.get('youtube') or {}; diff=youtube.get('differenceLayer') or {}
assert rumble.get('rendersRealQuestion') is True, rumble
region=diff.get('region') or (p.get('mask') or {}).get('region')
assert region == {'x':462,'y':104,'width':798,'height':470,'coordinateSpace':'pixels','referenceWidth':1280,'referenceHeight':720}, region
if diff.get('enabled') is True:
    assert diff.get('creativeKey') == 'yt_rumble_trivia_redirect', diff
    assert (p.get('adBreak') or {}).get('active') is False, p.get('adBreak')
    trivia=p.get('trivia') or {}
    assert str(trivia.get('phase') or '').lower() == 'question', trivia
    assert trivia.get('stale') is not True, trivia
    assert trivia.get('gameVisible') is True, trivia
    assert trivia.get('youtubeRedirectRequired') is True, trivia
assert health.get('workerVersion') == 'lovable-control-cache-v1', health
assert health.get('authority') == '/api/public/fgbears/stream-routing', health
assert health.get('ok') is True, health
last=float(health.get('lastGoodEpoch') or 0)
assert last > 0 and time.time()-last < 10, (last, time.time()-last if last else None)
print('CONTROL_STATE=PASS revision=%s difference=%s cache_age=%.2fs latency_ms=%s' % (state['revision'],str(bool(diff.get('enabled'))).lower(),time.time()-last,health.get('routingLatencyMs')))
PY

[[ -s "$PROGRESS" ]] || fail youtube_progress_missing
age=$(( $(date +%s) - $(stat -c %Y "$PROGRESS") ))
(( age < 10 )) || fail "youtube_progress_stale:${age}s"
rate=$(measure_rate) || fail youtube_rate_measurement_failed
python3 - "$rate" <<'PY' || fail youtube_below_realtime
import sys
assert float(sys.argv[1]) >= 0.98, sys.argv[1]
PY
fps=$(sed -n 's/^fps=\([0-9.]*\)$/\1/p' "$PROGRESS" | tail -n1)
drop=$(sed -n 's/^drop_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)
dup=$(sed -n 's/^dup_frames=\([0-9]*\)$/\1/p' "$PROGRESS" | tail -n1)

journal=$(journalctl -u "$YOUTUBE" --since '-10 seconds' --no-pager 2>/dev/null || true)
grep -Fq 'Circular buffer overrun' <<<"$journal" && fail youtube_udp_circular_buffer_overrun
if grep -Eq 'non-existing PPS|decode_slice_header error|no frame!' <<<"$journal"; then fail downstream_decoder_not_synchronized; fi

if [[ "$MODE" == final ]]; then
  for unit in "${RETIRED[@]}"; do
    systemctl is-active --quiet "$unit" && fail "retired_unit_active:$unit"
    state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
    [[ "$state" == masked* ]] || fail "retired_unit_not_masked:$unit:$state"
  done
  [[ -d "$V2_QUAR" ]] || fail v2_quarantine_missing
  if find "$V2_QUAR" -type f -perm /111 -print -quit 2>/dev/null | grep -q .; then fail v2_quarantine_contains_executable; fi
  [[ ! -e /opt/fgbears-live/youtube-v2 ]] || fail v2_active_runtime_present
  [[ -r "$GENERATION_FILE" ]] || fail generation_marker_missing
  [[ "$(cat "$GENERATION_FILE")" == v3 ]] || fail generation_marker_not_v3
  [[ -x "$HEALTHCHECK" ]] || fail healthcheck_missing
  grep -Fq 'recover_youtube_destination' "$HEALTHCHECK" || fail healthcheck_not_generation_aware
  grep -Fq 'YOUTUBE_GENERATION_FILE=' "$HEALTHCHECK" || fail healthcheck_generation_marker_missing
  grep -Fq 'YOUTUBE_CUTOVER_MARKER=' "$HEALTHCHECK" || fail healthcheck_cutover_guard_missing
fi

pressure=$(awk '/^some/{for(i=1;i<=NF;i++) if($i ~ /^avg10=/){split($i,a,"="); print a[2]}}' /proc/pressure/cpu 2>/dev/null || true)
printf 'YOUTUBE_V3_VERIFY=PASS mode=%s master=%s rumble=%s cache=%s youtube=%s youtube_restarts=%s steady_rate=%sx fps=%s drop=%s dup=%s cpu_pressure_avg10=%s rumble_1935=yes youtube_443=yes renderer_network=no v2=%s\n' \
  "$MODE" "$M" "$R" "$C" "$Y" "$(restarts "$Y")" "$rate" "${fps:-NA}" "${drop:-NA}" "${dup:-NA}" "${pressure:-NA}" "$([[ "$MODE" == final ]] && echo quarantined || echo rollback_ready)"

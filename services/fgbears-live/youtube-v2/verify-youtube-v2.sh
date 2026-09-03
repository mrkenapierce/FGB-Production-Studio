#!/usr/bin/env bash
set -Eeuo pipefail

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
CACHE=fgbears-lovable-state-cache.service
YOUTUBE=fgbears-youtube-v2.service
STATE=/run/fgbears-control-plane/stream-state.json
HEALTH=/run/fgbears-control-plane/cache-health.json
OVERLAY=/opt/fgbears-live/youtube-v2/youtube-v2-overlay.py
RETIRED=(
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
fail(){ echo "YOUTUBE_V2_VERIFY=FAIL reason=$1" >&2; exit 1; }

systemctl is-active --quiet "$MASTER" || fail master_inactive
systemctl is-active --quiet "$RUMBLE" || fail rumble_inactive
systemctl is-active --quiet "$CACHE" || fail control_cache_inactive
systemctl is-active --quiet "$YOUTUBE" || fail youtube_v2_inactive

M=$(pid "$MASTER"); R=$(pid "$RUMBLE"); C=$(pid "$CACHE"); Y=$(pid "$YOUTUBE")
[[ "$M" =~ ^[1-9][0-9]*$ ]] || fail invalid_master_pid
[[ "$R" =~ ^[1-9][0-9]*$ ]] || fail invalid_rumble_pid
[[ "$C" =~ ^[1-9][0-9]*$ ]] || fail invalid_cache_pid
[[ "$Y" =~ ^[1-9][0-9]*$ ]] || fail invalid_youtube_pid
connected "$R" 1935 || fail rumble_socket_missing
connected "$Y" 443 || fail youtube_socket_missing

# Hard architecture gate: renderer/media loop must contain no network client.
if grep -Eq 'urllib|urlopen|requests|http://|https://' "$OVERLAY"; then
  fail renderer_contains_network_io
fi

for unit in "${RETIRED[@]}"; do
  systemctl is-active --quiet "$unit" && fail "retired_unit_active:$unit"
  state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  [[ "$state" == masked* ]] || fail "retired_unit_not_masked:$unit:$state"
done

[[ -s "$STATE" ]] || fail control_state_missing
[[ -s "$HEALTH" ]] || fail cache_health_missing
python3 - "$STATE" "$HEALTH" <<'PY' || exit 1
from datetime import datetime
import json, sys, time
state=json.load(open(sys.argv[1], encoding='utf-8'))
health=json.load(open(sys.argv[2], encoding='utf-8'))
assert state.get('schemaVersion') == 'fgb-stream-state/v1', state.get('schemaVersion')
assert isinstance(state.get('revision'), str) and state['revision'], state.get('revision')
vu=state.get('validUntil')
assert isinstance(vu, str) and vu, vu
expiry=datetime.fromisoformat(vu.replace('Z','+00:00')).timestamp()
assert expiry > time.time(), (vu, expiry-time.time())
p=state.get('presentation') or {}
routing=p.get('routing') or {}
rumble=routing.get('rumble') or {}
youtube=routing.get('youtube') or {}
diff=youtube.get('differenceLayer') or {}
overlay=p.get('overlay') or {}
region=diff.get('region') or overlay.get('maskRegion')
assert rumble.get('rendersRealQuestion') is True, rumble
assert region == {
    'x':462,'y':104,'width':798,'height':470,
    'coordinateSpace':'pixels','referenceWidth':1280,'referenceHeight':720,
}, region
if diff.get('enabled') is True:
    assert diff.get('creativeKey') == 'yt_rumble_trivia_redirect', diff
    assert (p.get('adBreak') or {}).get('active') is False, p.get('adBreak')
    trivia=p.get('trivia') or {}
    assert str(trivia.get('phase') or '').lower() == 'question', trivia
    assert trivia.get('gameVisible') is True, trivia
    assert trivia.get('youtubeRedirectRequired') is True, trivia
assert health.get('ok') is True, health
last=float(health.get('lastGoodEpoch') or 0)
assert last > 0 and time.time()-last < 10, (last, time.time()-last if last else None)
print(f"CONTROL_STATE=PASS revision={state['revision']} difference={str(bool(diff.get('enabled'))).lower()} age={time.time()-last:.2f}s")
PY

# Validate running unit belongs to rebuilt executable without printing its
# command line, which contains the YouTube stream key in the FFmpeg target.
tr '\0' '\n' < "/proc/$Y/cmdline" | grep -q '/opt/fgbears-live/youtube-v2/run-youtube-v2.sh\|ffmpeg' || fail unexpected_youtube_process

printf 'YOUTUBE_V2_VERIFY=PASS master=%s rumble=%s cache=%s youtube=%s youtube_restarts=%s rumble_1935=yes youtube_443=yes renderer_network=no\n' \
  "$M" "$R" "$C" "$Y" "$(restarts "$Y")"

#!/usr/bin/env bash
set -Eeuo pipefail

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
YOUTUBE=fgbears-youtube-v2.service
STATE=/run/fgbears-youtube-v2/overlay-state.json
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
systemctl is-active --quiet "$YOUTUBE" || fail youtube_v2_inactive

M=$(pid "$MASTER"); R=$(pid "$RUMBLE"); Y=$(pid "$YOUTUBE")
[[ "$M" =~ ^[1-9][0-9]*$ ]] || fail invalid_master_pid
[[ "$R" =~ ^[1-9][0-9]*$ ]] || fail invalid_rumble_pid
[[ "$Y" =~ ^[1-9][0-9]*$ ]] || fail invalid_youtube_pid
connected "$R" 1935 || fail rumble_socket_missing
connected "$Y" 443 || fail youtube_socket_missing

for unit in "${RETIRED[@]}"; do
  systemctl is-active --quiet "$unit" && fail "retired_unit_active:$unit"
  state=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  [[ "$state" == masked* ]] || fail "retired_unit_not_masked:$unit:$state"
done

[[ -s "$STATE" ]] || fail overlay_state_missing
python3 - "$STATE" <<'PY' || exit 1
import json, sys, time
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p.get('maskRegion') == {
    'x':462,'y':104,'width':798,'height':470,
    'coordinateSpace':'pixels','referenceWidth':1280,'referenceHeight':720,
}, p.get('maskRegion')
assert p.get('frameSize') == [798,470], p.get('frameSize')
assert float(p.get('fps') or 0) == 10.0, p.get('fps')
last=float(p.get('lastGoodEpoch') or 0)
assert last > 0 and time.time()-last < 10, (last, time.time()-last if last else None)
print(f"OVERLAY_STATE=PASS phase={p.get('phase')} active={str(bool(p.get('active'))).lower()} age={time.time()-last:.2f}s")
PY

# Validate the running unit belongs to the rebuilt executable without printing
# its command line, which contains the YouTube stream key in the FFmpeg target.
tr '\0' '\n' < "/proc/$Y/cmdline" | grep -q '/opt/fgbears-live/youtube-v2/run-youtube-v2.sh\|ffmpeg' || fail unexpected_youtube_process

printf 'YOUTUBE_V2_VERIFY=PASS master=%s rumble=%s youtube=%s youtube_restarts=%s rumble_1935=yes youtube_443=yes\n' \
  "$M" "$R" "$Y" "$(restarts "$Y")"

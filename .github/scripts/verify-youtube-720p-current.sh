#!/usr/bin/env bash
set -Eeuo pipefail

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
LEGACY=fgbears-youtube-relay.service
HEALTH=http://127.0.0.1:8791/healthz
MONITOR=/run/fgbears-youtube-lovable-compositor
MASK_SOURCE=/opt/fgbears-live/bin/youtube-question-mask.py
PROGRESS=/srv/fgbears-live/logs/ffmpeg-progress.log

pid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
has_pid_port() {
  local p="$1" port="$2"
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  sudo ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v r=":$port" 'index($0,q)&&index($0,r){ok=1} END{exit(ok?0:1)}'
}
master_speed() {
  sudo awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); if(v!="") print v+0}' "$PROGRESS" 2>/dev/null || true
}

for u in "$MASTER" "$RUMBLE" "$COMP" "$ROUTING"; do systemctl is-active --quiet "$u"; done
! systemctl is-active --quiet "$LEGACY"
MASTER0=$(pid "$MASTER")
RUMBLE0=$(pid "$RUMBLE")
COMP0=$(pid "$COMP")
ROUTE0=$(pid "$ROUTING")
has_pid_port "$COMP0" 443
has_pid_port "$RUMBLE0" 1935

echo "LIVE_PIDS master=$MASTER0 rumble=$RUMBLE0 youtube=$COMP0 routing=$ROUTE0"

health=$(curl -fsS --max-time 3 "$HEALTH")
printf '%s' "$health" | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True,p
assert p.get("canvas")==[1280,720],p
assert p.get("maskRegion")=={"x":462,"y":104,"width":798,"height":470},p
assert p.get("frameSize")==[798,470],p
assert p.get("fps")==30,p
print("MASK_CONTRACT_720P=PASS phase={} active={}".format(p.get("phase"),p.get("active")))
'

# Monitor files rotate every two seconds. Wait through a few rotations instead
# of treating a boundary instant as an A/V failure.
seg=''
for _ in $(seq 1 15); do
  seg=$(find "$MONITOR" -maxdepth 1 -type f -name 'monitor-*.ts' -size +1000c -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1{sub(/^[^ ]+ /,"");print}' || true)
  [[ -n "$seg" ]] && break
  sleep 1
done
[[ -n "$seg" ]]
ffprobe -v error -show_streams -of json "$seg" | python3 -c '
import json,sys
p=json.load(sys.stdin); s=p.get("streams",[])
v=next(x for x in s if x.get("codec_type")=="video")
a=next(x for x in s if x.get("codec_type")=="audio")
assert (int(v.get("width",0)),int(v.get("height",0)))==(1280,720),v
assert v.get("r_frame_rate") in {"30/1","60/2"},v
assert int(a.get("sample_rate",0))==44100,a
assert int(a.get("channels",0))==2,a
print("YOUTUBE_AV=PASS video=1280x720@30 audio=44100Hz/2ch")
'

# Deterministically exercise the installed State class without importing the
# module's network/bootstrap side effects. This proves the deployed code latches
# through transient false/stale flags and errors, then clears on phase exit.
python3 - "$MASK_SOURCE" <<'PY'
import ast, pathlib, threading, time, sys
src=pathlib.Path(sys.argv[1]).read_text()
tree=ast.parse(src)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='State')
mod=ast.Module(body=[cls],type_ignores=[])
contract=object()
ns={
    'threading':threading,
    'time':time,
    'Any':object,
    'CONTRACT':contract,
    'STALE_SECONDS':30,
    'parse_contract':lambda payload: contract,
}
exec(compile(ast.fix_missing_locations(mod),'<state-test>','exec'),ns)
State=ns['State']; s=State()
base={'trivia':{'phase':'question','youtubeMaskActive':True,'stale':False,'adsVisible':False,'isAdBreak':False,'adBreakActive':False}}
s.update(base)
assert s.snapshot()[0] is True
transient={'trivia':{'phase':'question','youtubeMaskActive':False,'stale':True,'adsVisible':False,'isAdBreak':False,'adBreakActive':False}}
s.update(transient)
assert s.snapshot()[0] is True
s.error(RuntimeError('synthetic transient'))
assert s.snapshot()[0] is True
end={'trivia':{'phase':'answer','youtubeMaskActive':False,'stale':False,'adsVisible':False,'isAdBreak':False,'adBreakActive':False}}
s.update(end)
assert s.snapshot()[0] is False
print('QUESTION_LATCH_STATE_MACHINE=PASS')
PY

# Observe sustained production stability rather than trusting one snapshot.
# At the same time, if a question is live, every sampled question frame must
# report the cover active. This catches any visible drop during the audit window.
max_cpu=0
min_speed=999
question_samples=0
for i in $(seq 1 20); do
  [[ "$(pid "$MASTER")" == "$MASTER0" ]]
  [[ "$(pid "$RUMBLE")" == "$RUMBLE0" ]]
  [[ "$(pid "$COMP")" == "$COMP0" ]]
  [[ "$(pid "$ROUTING")" == "$ROUTE0" ]]
  has_pid_port "$COMP0" 443
  has_pid_port "$RUMBLE0" 1935
  cpu=$(ps -p "$COMP0" -o %cpu= | tr -d ' ')
  speed=$(master_speed)
  if [[ -n "$speed" ]]; then
    python3 -c 'import sys; assert float(sys.argv[1]) >= 0.99, sys.argv[1]' "$speed"
    min_speed=$(python3 -c 'import sys; print(min(float(sys.argv[1]),float(sys.argv[2])))' "$min_speed" "$speed")
  fi
  max_cpu=$(python3 -c 'import sys; print(max(float(sys.argv[1]),float(sys.argv[2])))' "$max_cpu" "$cpu")

  h=$(curl -fsS --max-time 2 "$HEALTH")
  q=$(printf '%s' "$h" | python3 -c 'import json,sys;p=json.load(sys.stdin);print("Q1" if p.get("phase")=="question" and p.get("active") is True else ("Q0" if p.get("phase")=="question" else "N"))')
  [[ "$q" != Q0 ]]
  [[ "$q" == Q1 ]] && question_samples=$((question_samples+1))
  sleep 1
done
python3 -c 'import sys; assert float(sys.argv[1]) <= 50.0, sys.argv[1]' "$max_cpu"
echo "STABILITY_20S=PASS min_master_speed=${min_speed}x max_compositor_cpu=${max_cpu}%"
if (( question_samples > 0 )); then
  echo "LIVE_QUESTION_WINDOW=PASS active_samples=$question_samples"
else
  echo 'LIVE_QUESTION_WINDOW=NOT_ACTIVE_AT_AUDIT'
fi

echo 'YOUTUBE_720P_CURRENT_AUDIT=PASS'

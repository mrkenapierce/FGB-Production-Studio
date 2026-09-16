#!/usr/bin/env bash
set -Eeuo pipefail
MASTER=fgbears-live.service
AUDIO=/srv/fgbears-live/audio/fgb-music-loop.m4a
STAGE=/srv/fgbears-live/audio/incoming/recovery-episode034
STATE=/srv/fgbears-live/runtime/lovable-audio-pipeline.json
SOURCE_SHA=c5c53890601ee446fe38d267f7cf5dba5dd899fba45006a8ddbb60d88654e66c
PROGRESS=/srv/fgbears-live/logs/ffmpeg-progress.log
Q=/srv/fgbears-live/quarantine/episode034-recovery

systemctl is-active --quiet "$MASTER"
test "$(systemctl is-active fgbears-lovable-audio-sync.timer || true)" = inactive
curl -fsS --max-time 20 https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing -o /tmp/fgb-contract.json
jq -e --arg sha "$SOURCE_SHA" '.presentation.audio.revision==7 and .presentation.audio.approvalState=="approved" and .presentation.audio.activeTrackName=="Episode 034" and .presentation.audio.sourceSha256==$sha and .presentation.audio.enabled==true and .presentation.audio.loop==true and .presentation.audio.mode=="track"' /tmp/fgb-contract.json >/dev/null

test -s "$STAGE/candidate.m4a" && test -s "$STAGE/candidate.m4a.audio-profile.json" && test -s "$STAGE/canonical.sha256"
expected_sha=$(awk '{print $1}' "$STAGE/canonical.sha256")
stage_sha=$(sha256sum "$STAGE/candidate.m4a" | awk '{print $1}')
test "$expected_sha" = "$stage_sha"
jq -e --arg source "$SOURCE_SHA" '.profile=="fgb-clean-static-v3" and .quality_verified==true and .dynamic_processing==false and .source_sha256==$source and .audio_codec=="aac" and .sample_rate_hz==48000 and .channels==2 and .output_metrics.tp_dbtp<=-1.5 and (.output_metrics.i_lufs>=-18 and .output_metrics.i_lufs<=-14.5)' "$STAGE/candidate.m4a.audio-profile.json" >/dev/null
ffmpeg -hide_banner -nostdin -v error -xerror -i "$STAGE/candidate.m4a" -map 0:a:0 -vn -f null -
echo "REV7_PREFLIGHT=PASS canonical_sha256=$stage_sha"

mkdir -p "$Q"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$Q/$stamp-pre-rev7.m4a"
old_sha=$(sha256sum "$AUDIO" | awk '{print $1}')
cp -p "$AUDIO" "$BACKUP"
mapfile -t destinations < <(systemctl list-units --type=service --state=running --no-legend --no-pager 'fgbears-*' | awk '{print $1}' | grep -E 'youtube|rumble|facebook|relay|uplink' || true)

pacing_ratio() {
  python3 - "$PROGRESS" <<'PY'
import sys,time
p=sys.argv[1]; samples=[]
def readv():
    v=None
    try:
        for line in open(p,errors='ignore'):
            if line.startswith('out_time_us=') or line.startswith('out_time_ms='):
                try: v=int(line.split('=',1)[1])
                except: pass
    except FileNotFoundError: pass
    return v
for _ in range(31):
    v=readv()
    if v is not None: samples.append((time.monotonic(),v/1_000_000.0))
    time.sleep(1)
if len(samples)<20: raise SystemExit('insufficient progress samples')
t0=samples[0][0]; xs=[t-t0 for t,_ in samples]; ys=[m for _,m in samples]
xm=sum(xs)/len(xs); ym=sum(ys)/len(ys); den=sum((x-xm)**2 for x in xs)
slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/den
print(f'{slope:.6f}')
PY
}

rollback() {
  reason="$1"
  echo "CUTOVER_FAILURE=$reason" >&2
  cp -p "$BACKUP" "$AUDIO.rollback"
  chown fgbears:fgbears "$AUDIO.rollback"; chmod 0644 "$AUDIO.rollback"
  mv -f "$AUDIO.rollback" "$AUDIO"
  systemctl reset-failed "$MASTER" || true
  systemctl restart "$MASTER" || true
  sleep 5
  restored=$(sha256sum "$AUDIO" | awk '{print $1}')
  test "$restored" = "$old_sha"
  python3 - "$STATE" "$reason" <<'PY'
import json,sys,time,os
p,reason=sys.argv[1:]
try: s=json.load(open(p))
except: s={}
failed={int(x) for x in s.get('failedRevisions',[]) if str(x).isdigit()}; failed.update({4,7})
s.update(status='rolled_back',candidateRevision=7,failedRevisions=sorted(failed),message=reason,completedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
t=p+'.tmp'; open(t,'w').write(json.dumps(s,indent=2,sort_keys=True)+'\n'); os.replace(t,p)
PY
  exit 1
}

cp -p "$STAGE/candidate.m4a" "$AUDIO.new"
chown fgbears:fgbears "$AUDIO.new"; chmod 0644 "$AUDIO.new"
mv -f "$AUDIO.new" "$AUDIO"
systemctl reset-failed "$MASTER" || true
systemctl restart "$MASTER" || rollback 'master restart failed'

deadline=$((SECONDS+60)); opened=no
while (( SECONDS < deadline )); do
  if systemctl is-active --quiet "$MASTER"; then
    mpid=$(systemctl show -p MainPID --value "$MASTER")
    ffpid=$(pgrep -P "$mpid" -x ffmpeg | head -1 || true)
    if [[ -n "$ffpid" ]] && ls -l "/proc/$ffpid/fd" 2>/dev/null | grep -Fq "$AUDIO"; then opened=yes; break; fi
  fi
  sleep 1
done
[[ "$opened" == yes ]] || rollback 'master did not reopen canonical audio'

codec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$AUDIO")
rate=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=nw=1:nk=1 "$AUDIO")
channels=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=nw=1:nk=1 "$AUDIO")
[[ "$codec" == aac && "$rate" == 48000 && "$channels" == 2 ]] || rollback 'live audio signature mismatch'
canonical_sha=$(sha256sum "$AUDIO" | awk '{print $1}')
[[ "$canonical_sha" == "$expected_sha" ]] || rollback 'live candidate hash mismatch'

ratio=$(pacing_ratio) || rollback 'unable to measure new-audio pacing'
python3 - "$ratio" <<'PY' || rollback "new audio pacing ratio $ratio outside 0.98-1.02"
import sys
r=float(sys.argv[1]); raise SystemExit(0 if 0.98 <= r <= 1.02 else 1)
PY

for unit in "${destinations[@]}"; do
  systemctl is-active --quiet "$unit" || rollback "destination stopped: $unit"
done
if systemctl is-active --quiet fgbears-youtube-copy-relay.service; then
  ymain=$(systemctl show -p MainPID --value fgbears-youtube-copy-relay.service)
  ps -eo pid=,ppid=,args= | awk -v p="$ymain" '$1==p || $2==p' | grep -Eq -- '-c( |:a )copy' || rollback 'YouTube copy/remux invariant not visible'
fi

python3 - "$STATE" "$canonical_sha" "$ratio" "$SOURCE_SHA" <<'PY'
import json,sys,time,os
p,canon,ratio,source=sys.argv[1:]
try: s=json.load(open(p))
except: s={}
failed={int(x) for x in s.get('failedRevisions',[]) if str(x).isdigit()}; failed.add(4); failed.discard(7)
s.update(appliedRevision=7,candidateRevision=7,activeTrackId='8c5d75a7-47c8-490c-8904-0c78b0140e09',activeTrackName='Episode 034',sourceSha256=source,canonicalSha256=canon,pacingRatio=float(ratio),status='live',shadow=False,failedRevisions=sorted(failed),message='Off-host mastered Episode 034 deployed and verified',completedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
t=p+'.tmp'; open(t,'w').write(json.dumps(s,indent=2,sort_keys=True)+'\n'); os.replace(t,p)
PY

echo "EPISODE_034_ACTIVATION=PASS revision=7 pacing=$ratio canonical_sha256=$canonical_sha"
echo "TIMER_REMAINS_INACTIVE=yes"

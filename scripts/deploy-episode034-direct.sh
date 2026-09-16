#!/usr/bin/env bash
set -Eeuo pipefail
MASTER=fgbears-live.service
TIMER=fgbears-lovable-audio-sync.timer
AUDIO=/srv/fgbears-live/audio/fgb-music-loop.m4a
STATE=/srv/fgbears-live/runtime/lovable-audio-pipeline.json
TRACK_ID=efe3d120-2fab-4bca-a08e-fccd32364f5f
EXPECTED_SHA=c04e4fa32a5acc4200c2ef88e8bf43f7618998768ad8c58a716f7869a35a9e7a
CONTRACT=https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing
ASSET=https://epiccontentcreatorgrants.org/api/public/fgbears/audio-asset/$TRACK_ID
STAGE=/srv/fgbears-live/audio/incoming/episode034-production-ready-direct.m4a
Q=/srv/fgbears-live/quarantine/episode034-direct

systemctl is-active --quiet "$MASTER"
systemctl disable --now "$TIMER" >/dev/null 2>&1 || true
curl -fsS --max-time 20 "$CONTRACT" -o /tmp/fgb-contract.json
jq -e --arg sha "$EXPECTED_SHA" --arg tid "$TRACK_ID" '.presentation.audio.revision==9 and .presentation.audio.approvalState=="approved" and .presentation.audio.activeTrackId==$tid and .presentation.audio.sourceSha256==$sha and .presentation.audio.enabled==true and .presentation.audio.loop==true and .presentation.audio.mode=="track"' /tmp/fgb-contract.json >/dev/null

mkdir -p "$(dirname "$STAGE")" "$Q"
rm -f "$STAGE.tmp"
curl -fL --retry 3 --max-time 180 "$ASSET" -o "$STAGE.tmp"
test "$(sha256sum "$STAGE.tmp" | awk '{print $1}')" = "$EXPECTED_SHA"
codec=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$STAGE.tmp")
rate=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=nw=1:nk=1 "$STAGE.tmp")
channels=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=nw=1:nk=1 "$STAGE.tmp")
[[ "$codec" == aac && "$rate" == 48000 && "$channels" == 2 ]]
mv -f "$STAGE.tmp" "$STAGE"
chown fgbears:fgbears "$STAGE"; chmod 0644 "$STAGE"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$Q/$stamp-pre-direct.m4a"
cp -p "$AUDIO" "$BACKUP"
mapfile -t destinations < <(systemctl list-units --type=service --state=running --no-legend --no-pager 'fgbears-*' | awk '{print $1}' | grep -E 'youtube|rumble|facebook|relay|uplink' || true)

rollback(){ cp -p "$BACKUP" "$AUDIO.rollback"; chown fgbears:fgbears "$AUDIO.rollback"; chmod 0644 "$AUDIO.rollback"; mv -f "$AUDIO.rollback" "$AUDIO"; systemctl reset-failed "$MASTER" || true; systemctl restart "$MASTER" || true; exit 1; }
cp -p "$STAGE" "$AUDIO.new"; chown fgbears:fgbears "$AUDIO.new"; chmod 0644 "$AUDIO.new"; mv -f "$AUDIO.new" "$AUDIO"
systemctl reset-failed "$MASTER" || true
systemctl restart "$MASTER" || rollback
sleep 6
systemctl is-active --quiet "$MASTER" || rollback
test "$(sha256sum "$AUDIO" | awk '{print $1}')" = "$EXPECTED_SHA" || rollback
mpid=$(systemctl show -p MainPID --value "$MASTER")
ffpid=$(pgrep -P "$mpid" -x ffmpeg | head -1 || true)
[[ -n "$ffpid" ]] || rollback
ls -l "/proc/$ffpid/fd" 2>/dev/null | grep -Fq "$AUDIO" || rollback
for unit in "${destinations[@]}"; do systemctl is-active --quiet "$unit" || rollback; done

python3 - "$STATE" "$EXPECTED_SHA" "$TRACK_ID" <<'PY'
import json,sys,time,os
p,sha,tid=sys.argv[1:]
try:s=json.load(open(p))
except:s={}
failed={int(x) for x in s.get('failedRevisions',[]) if str(x).isdigit()}; failed.update({4,7}); failed.discard(9)
s.update(appliedRevision=9,observedRevision=9,candidateRevision=9,activeTrackId=tid,activeTrackName='FGB_Episode_034_PRODUCTION_READY_NO_PROCESSING.m4a',sourceSha256=sha,canonicalSha256=sha,status='live',shadow=False,failedRevisions=sorted(failed),message='Exact production-ready Episode 034 M4A deployed with no processing',completedAt=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
t=p+'.tmp'; open(t,'w').write(json.dumps(s,indent=2,sort_keys=True)+'\n'); os.replace(t,p)
PY

echo EPISODE_034_DIRECT_DEPLOY=PASS
echo LIVE_SHA=$(sha256sum "$AUDIO" | awk '{print $1}')
echo MASTER_PID=$(systemctl show -p MainPID --value "$MASTER")
echo AUTO_SYNC_TIMER=$(systemctl is-active "$TIMER" || true)
echo ACTIVE_DESTINATIONS=${destinations[*]:-none}
# trigger direct deployment after workflow registration

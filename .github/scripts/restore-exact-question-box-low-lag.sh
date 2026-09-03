#!/usr/bin/env bash
set -Eeuo pipefail

: "${ORACLE_HOST:?ORACLE_HOST required}"
: "${ORACLE_SSH_KEY:?ORACLE_SSH_KEY required}"
TARGET="${ORACLE_USER:-ubuntu}@$ORACLE_HOST"

install -d -m 700 ~/.ssh
printf '%s\n' "$ORACLE_SSH_KEY" > ~/.ssh/oracle_key
chmod 600 ~/.ssh/oracle_key
ssh-keyscan -H "$ORACLE_HOST" >> ~/.ssh/known_hosts

mkdir -p stage
# Restore the measured safety-qualified 640x360 compositor implementation.
git show 6b88e4ea368fdb1b05ad2ba43b2fe5c0a4067617:services/fgbears-live/bin/youtube-lovable-compositor.sh > stage/youtube-lovable-compositor.sh

# Keep the current question-phase concealment protection, but execute only the
# authoritative question rectangle instead of the erroneous full middle band.
python3 - <<'PY'
from pathlib import Path
src=Path('services/fgbears-live/bin/youtube-question-mask.py').read_text()
old='''    # The API region above remains authoritative and is fully validated. For\n    # execution, protect the complete middle program band. This is intentionally\n    # conservative: news remains live above y=104 and crawl remains live at/after\n    # y=574, while every pixel capable of containing a trivia question is covered.\n    output_news_bottom = scaled(SOURCE_NEWS_BOTTOM, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    output_crawl_top = scaled(SOURCE_CRAWL_TOP, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    x = 0\n    y = output_news_bottom\n    width = OUTPUT_CANVAS_WIDTH\n    height = output_crawl_top - output_news_bottom\n    if width <= 0 or height <= 0 or x < 0 or y < 0:\n        raise ValueError("invalid full-middle YouTube protection region")\n    if x + width > OUTPUT_CANVAS_WIDTH or y + height > OUTPUT_CANVAS_HEIGHT:\n        raise ValueError("full-middle YouTube protection region exceeds execution canvas")\n'''
new='''    # Execute exactly the Lovable-authoritative question rectangle.\n    x = scaled(source_x, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)\n    y = scaled(source_y, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    width = scaled(source_width, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)\n    height = scaled(source_height, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    output_news_bottom = scaled(SOURCE_NEWS_BOTTOM, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    output_crawl_top = scaled(SOURCE_CRAWL_TOP, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)\n    if width <= 0 or height <= 0 or x < 0 or y < output_news_bottom or y + height > output_crawl_top:\n        raise ValueError("scaled maskRegion would overlap the always-live news or crawl bands")\n    if x + width > OUTPUT_CANVAS_WIDTH or y + height > OUTPUT_CANVAS_HEIGHT:\n        raise ValueError("scaled maskRegion exceeds the YouTube execution canvas")\n'''
if old in src:
    src=src.replace(old,new).replace('"executionScaling": "full_middle_protection"','"executionScaling": "proportional_downstream"')
Path('stage/youtube-question-mask.py').write_text(src)

comp=Path('services/fgbears-live/systemd/fgbears-youtube-lovable-compositor.service').read_text()
comp=comp.replace('Description=FGBears YouTube Lovable-Controlled 720p Compositor','Description=FGBears YouTube Lovable-Controlled Resource-Protected 360p Compositor')
comp=comp.replace('Environment=YOUTUBE_OUTPUT_WIDTH=1280','Environment=YOUTUBE_OUTPUT_WIDTH=640')
comp=comp.replace('Environment=YOUTUBE_OUTPUT_HEIGHT=720','Environment=YOUTUBE_OUTPUT_HEIGHT=360')
Path('stage/fgbears-youtube-lovable-compositor.service').write_text(comp)
route=Path('services/fgbears-live/systemd/fgbears-youtube-lovable-routing.service').read_text()
route=route.replace('Environment=YOUTUBE_OUTPUT_CANVAS_WIDTH=1280','Environment=YOUTUBE_OUTPUT_CANVAS_WIDTH=640')
route=route.replace('Environment=YOUTUBE_OUTPUT_CANVAS_HEIGHT=720','Environment=YOUTUBE_OUTPUT_CANVAS_HEIGHT=360')
Path('stage/fgbears-youtube-lovable-routing.service').write_text(route)
PY
chmod 755 stage/youtube-lovable-compositor.sh stage/youtube-question-mask.py

scp -i ~/.ssh/oracle_key \
  stage/youtube-lovable-compositor.sh \
  stage/youtube-question-mask.py \
  stage/fgbears-youtube-lovable-compositor.service \
  stage/fgbears-youtube-lovable-routing.service \
  "$TARGET:/tmp/"

ssh -i ~/.ssh/oracle_key "$TARGET" 'sudo bash -s' <<'REMOTE'
set -Eeuo pipefail
MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
LEGACY=fgbears-youtube-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
COMP_SCRIPT=/opt/fgbears-live/bin/youtube-lovable-compositor.sh
MASK_SCRIPT=/opt/fgbears-live/bin/youtube-question-mask.py
COMP_UNIT=/etc/systemd/system/fgbears-youtube-lovable-compositor.service
ROUTING_UNIT=/etc/systemd/system/fgbears-youtube-lovable-routing.service
BACKUP=$(mktemp -d /tmp/fgb-youtube-exact360.XXXXXX)
SUCCESS=0
active(){ systemctl is-active --quiet "$1"; }
pid(){ systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
has_port(){ local p="$1" q="$2"; [[ "$p" =~ ^[1-9][0-9]*$ ]] && ss -ntpH state established 2>/dev/null | awk -v p="pid=$p" -v q=":$q" 'index($0,p)&&index($0,q){ok=1} END{exit(ok?0:1)}'; }
speed(){ awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); if(v!="") print v+0}' /srv/fgbears-live/logs/ffmpeg-progress.log 2>/dev/null || true; }
rollback(){
  rc=$?
  (( SUCCESS == 0 )) || return 0
  echo "EXACT360_ROLLBACK=BEGIN rc=$rc"
  systemctl stop "$COMP" "$ROUTING" 2>/dev/null || true
  [[ -f "$BACKUP/compositor.sh" ]] && install -m 0755 "$BACKUP/compositor.sh" "$COMP_SCRIPT" || true
  [[ -f "$BACKUP/mask.py" ]] && install -m 0755 "$BACKUP/mask.py" "$MASK_SCRIPT" || true
  [[ -f "$BACKUP/compositor.service" ]] && install -m 0644 "$BACKUP/compositor.service" "$COMP_UNIT" || true
  [[ -f "$BACKUP/routing.service" ]] && install -m 0644 "$BACKUP/routing.service" "$ROUTING_UNIT" || true
  systemctl daemon-reload || true
  systemctl stop "$LEGACY" 2>/dev/null || true
  systemctl disable "$LEGACY" >/dev/null 2>&1 || true
  systemctl reset-failed "$ROUTING" "$COMP" >/dev/null 2>&1 || true
  systemctl start "$ROUTING" || true
  systemctl start "$COMP" || true
  echo "EXACT360_ROLLBACK_OWNER=COMPOSITOR master=$(pid "$MASTER") rumble=$(pid "$RUMBLE") compositor=$(pid "$COMP")"
  rm -rf "$BACKUP"
  exit "$rc"
}
trap rollback EXIT

active "$MASTER"; active "$RUMBLE"
MASTER0=$(pid "$MASTER"); RUMBLE0=$(pid "$RUMBLE"); COMP0=$(pid "$COMP"); SPEED0=$(speed)
echo "PRE master=$MASTER0 rumble=$RUMBLE0 compositor=$COMP0 speed=${SPEED0:-unknown} load=$(cut -d' ' -f1-3 /proc/loadavg)"
has_port "$RUMBLE0" 1935
cp -a "$COMP_SCRIPT" "$BACKUP/compositor.sh"
cp -a "$MASK_SCRIPT" "$BACKUP/mask.py"
cp -a "$COMP_UNIT" "$BACKUP/compositor.service"
cp -a "$ROUTING_UNIT" "$BACKUP/routing.service"

install -m 0755 /tmp/youtube-lovable-compositor.sh "$COMP_SCRIPT"
install -m 0755 /tmp/youtube-question-mask.py "$MASK_SCRIPT"
install -m 0644 /tmp/fgbears-youtube-lovable-compositor.service "$COMP_UNIT"
install -m 0644 /tmp/fgbears-youtube-lovable-routing.service "$ROUTING_UNIT"
systemctl daemon-reload
systemctl enable "$COMP" "$ROUTING" >/dev/null
systemctl stop "$LEGACY" 2>/dev/null || true
systemctl disable "$LEGACY" >/dev/null 2>&1 || true
systemctl stop "$COMP" 2>/dev/null || true
systemctl restart "$ROUTING"

MASK_OK=0; health=''
for _ in $(seq 1 25); do
  if health=$(curl -fsS --max-time 2 http://127.0.0.1:8791/healthz 2>/dev/null); then
    if printf '%s' "$health" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True;assert p.get("canvas")==[640,360],p;assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470},p;assert p.get("maskRegion")=={"x":231,"y":52,"width":399,"height":235},p;assert p.get("executionScaling")=="proportional_downstream",p;assert p.get("failClosedDuringQuestion") is True,p;assert p.get("fps")==30,p' 2>/dev/null; then MASK_OK=1; break; fi
  fi
  sleep 1
done
(( MASK_OK == 1 ))
echo "EXACT_QUESTION_BOX=PASS $health"

systemctl reset-failed "$COMP" || true
systemctl start "$COMP"
CONNECTED=0
for _ in $(seq 1 30); do COMP1=$(pid "$COMP"); if active "$COMP" && has_port "$COMP1" 443; then CONNECTED=1; break; fi; sleep 1; done
(( CONNECTED == 1 ))
echo "YOUTUBE_OWNER=EXACT360_COMPOSITOR pid=$COMP1"

SEG=''
for _ in $(seq 1 20); do
  SEG=$(find /run/fgbears-youtube-lovable-compositor -maxdepth 1 -type f -name 'monitor-*.ts' -size +1000c -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1{sub(/^[^ ]+ /,"");print}' || true)
  [[ -n "$SEG" ]] && break
  sleep 1
done
[[ -n "$SEG" ]]
ffprobe -v error -show_streams -of json "$SEG" | python3 -c 'import json,sys;p=json.load(sys.stdin);s=p.get("streams",[]);v=next(x for x in s if x.get("codec_type")=="video");a=next(x for x in s if x.get("codec_type")=="audio");assert (int(v.get("width",0)),int(v.get("height",0)))==(640,360),v;assert v.get("r_frame_rate") in {"30/1","60/2"},v;assert int(a.get("sample_rate",0))==48000,a;assert int(a.get("channels",0))==2,a;print("YOUTUBE_AV=PASS 640x360@30 audio=48000Hz/2ch")'
[[ "$(pid "$MASTER")" == "$MASTER0" ]]; [[ "$(pid "$RUMBLE")" == "$RUMBLE0" ]]; has_port "$RUMBLE0" 1935
sleep 20
COMP2=$(pid "$COMP"); [[ "$COMP2" == "$COMP1" ]]; has_port "$COMP2" 443
CPU=$(ps -p "$COMP2" -o %cpu= | tr -d ' '); SPEED=$(speed)
echo "POST_RESOURCE compositor_cpu=${CPU}% master_speed=${SPEED:-unknown}x load=$(cut -d' ' -f1-3 /proc/loadavg)"
python3 -c 'import sys;c=float(sys.argv[1]);assert c<=40.0,c' "$CPU"
if [[ -n "$SPEED" ]]; then python3 -c 'import sys;s=float(sys.argv[1]);assert s>=0.985,s' "$SPEED"; fi
[[ "$(pid "$MASTER")" == "$MASTER0" ]]; [[ "$(pid "$RUMBLE")" == "$RUMBLE0" ]]; has_port "$RUMBLE0" 1935; has_port "$COMP2" 443; ! active "$LEGACY"
echo "EXACT360_CUTOVER=PASS master=$MASTER0 rumble=$RUMBLE0 youtube=$COMP2"
SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/youtube-lovable-compositor.sh /tmp/youtube-question-mask.py /tmp/fgbears-youtube-lovable-compositor.service /tmp/fgbears-youtube-lovable-routing.service
REMOTE

#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 77; }

MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
ENV=/etc/fgbears-live/stream.env
BACKUP=$(mktemp -d /tmp/fgb-ticker-backup.XXXXXX)
SUCCESS=0
CHANGED=0

active() { systemctl is-active --quiet "$1"; }
mainpid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
ffpid() {
  local p
  p=$(mainpid "$1")
  [[ "$p" =~ ^[1-9][0-9]*$ ]] || return 1
  if [[ "$(cat /proc/$p/comm 2>/dev/null || true)" == ffmpeg ]]; then
    echo "$p"
  else
    pgrep -P "$p" -x ffmpeg 2>/dev/null | sed -n '1p'
  fi
}
has_port() {
  local p="$1" port="$2"
  ss -ntpH state established 2>/dev/null | awk -v q="pid=$p" -v r=":$port" 'index($0,q)&&index($0,r){x=1} END{exit(x?0:1)}'
}
rumble_connected() { local p; p=$(ffpid "$RUMBLE" || true); [[ "$p" =~ ^[1-9][0-9]*$ ]] && has_port "$p" 1935; }
youtube_connected() { local p; p=$(ffpid "$COMP" || true); [[ "$p" =~ ^[1-9][0-9]*$ ]] && has_port "$p" 443; }

rollback() {
  local rc=$?
  if (( SUCCESS == 1 )); then
    rm -rf "$BACKUP"
    exit 0
  fi
  echo "ROLLBACK=TICKERS_BEGIN rc=$rc"
  if (( CHANGED == 1 )); then
    [[ -f "$BACKUP/crawl-overlay-hq.py" ]] && install -m 0755 "$BACKUP/crawl-overlay-hq.py" /opt/fgbears-live/bin/crawl-overlay-hq.py || true
    if [[ -f "$BACKUP/bears-news-feed-hq.py" ]]; then
      install -m 0755 "$BACKUP/bears-news-feed-hq.py" /opt/fgbears-live/bin/bears-news-feed-hq.py || true
    else
      rm -f /opt/fgbears-live/bin/bears-news-feed-hq.py || true
    fi
    install -m 0755 "$BACKUP/fgbears-start-stream" /usr/local/bin/fgbears-start-stream || true
    cp -a "$BACKUP/stream.env" "$ENV" || true
    systemctl restart "$MASTER" || true
    sleep 10
  fi
  rm -rf "$BACKUP"
  echo "ROLLBACK=TICKERS_COMPLETE"
  exit "$rc"
}
trap rollback EXIT

active "$MASTER"
active "$RUMBLE"
active "$COMP"
active "$ROUTING"
rumble_connected
youtube_connected
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
COMP0=$(mainpid "$COMP")
echo "PRE master=$MASTER0 rumble=$RUMBLE0 compositor=$COMP0 load=$(cut -d' ' -f1-3 /proc/loadavg)"

cp -a /opt/fgbears-live/bin/crawl-overlay-hq.py "$BACKUP/crawl-overlay-hq.py"
[[ ! -e /opt/fgbears-live/bin/bears-news-feed-hq.py ]] || cp -a /opt/fgbears-live/bin/bears-news-feed-hq.py "$BACKUP/bears-news-feed-hq.py"
cp -a /usr/local/bin/fgbears-start-stream "$BACKUP/fgbears-start-stream"
cp -a "$ENV" "$BACKUP/stream.env"
CHANGED=1

install -m 0755 /tmp/bears-news-feed-hq.py /opt/fgbears-live/bin/bears-news-feed-hq.py
install -m 0755 /tmp/crawl-overlay-hq.py /opt/fgbears-live/bin/crawl-overlay-hq.py
install -m 0755 /tmp/start-stream.sh /usr/local/bin/fgbears-start-stream

python3 - "$ENV" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = path.read_text(encoding='utf-8').splitlines()
updates = {
    'OUTPUT_FPS': '30',
    'CRAWL_OVERLAY_SCRIPT': '/opt/fgbears-live/bin/crawl-overlay-hq.py',
    'CRAWL_OVERLAY_FPS': '30',
    'CRAWL_TEXT_RENDER_SCALE': '2',
    'BEARS_NEWS_SCRIPT': '/opt/fgbears-live/bin/bears-news-feed-hq.py',
    'BEARS_NEWS_OVERLAY_FPS': '30',
    'BEARS_NEWS_SCROLL_PPS': '76',
}
seen=set(); out=[]
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0]
        if key in updates:
            if key not in seen:
                out.append(f'{key}={updates[key]}'); seen.add(key)
            continue
    out.append(line)
for key,value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
path.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chown root:fgbears "$ENV"
chmod 0640 "$ENV"

python3 -m py_compile \
  /opt/fgbears-live/bin/bears-news-feed.py \
  /opt/fgbears-live/bin/bears-news-feed-hq.py \
  /opt/fgbears-live/bin/crawl-overlay.py \
  /opt/fgbears-live/bin/crawl-overlay-hq.py

python3 - <<'PY'
import importlib.util

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
rss=load('rsshq','/opt/fgbears-live/bin/bears-news-feed-hq.py')
assert rss.BASE.FPS == 30
rss.STATE.update('FIRST HEADLINE')
rss.STATE.update('SECOND HEADLINE')
assert rss.STATE.pending_chars() > 0
crawl=load('crawlhq','/opt/fgbears-live/bin/crawl-overlay-hq.py')
s=crawl.BoundarySequence(); now=1.0
assert s.select({'active':True,'messages':['ONE','TWO']},now)[0]=='ONE'
assert s.select({'active':True,'messages':['THREE']},now+1)[0]=='ONE'
assert s.pending_count()==1
assert s.advance_if_complete(-100000,100,now+2)
assert s.select({'active':True,'messages':['THREE']},now+2)[0]=='THREE'
print('STATIC_TICKER_TESTS=PASS')
PY

systemctl restart "$MASTER"
for _ in $(seq 1 45); do
  if active "$MASTER" && curl -fsS --max-time 2 http://127.0.0.1:8788/healthz >/dev/null 2>&1 && curl -fsS --max-time 2 http://127.0.0.1:8789/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
active "$MASTER"
MASTER1=$(mainpid "$MASTER")
[[ "$MASTER1" =~ ^[1-9][0-9]*$ && "$MASTER1" != "$MASTER0" ]]

RSS_HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:8789/healthz)
printf '%s' "$RSS_HEALTH" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;assert p.get("scrollPps")==76,p;assert p.get("payloadSwap")=="next-cycle-boundary",p;print("RSS_CONTRACT=PASS")'
CRAWL_HEALTH=$(curl -fsS --max-time 3 http://127.0.0.1:8788/healthz)
printf '%s' "$CRAWL_HEALTH" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;print("CRAWL_CONTRACT=PASS")'

pgrep -P "$MASTER1" -af 'bears-news-feed-hq.py' >/dev/null
pgrep -P "$MASTER1" -af 'crawl-overlay-hq.py' >/dev/null
MASTER_FF=$(pgrep -P "$MASTER1" -x ffmpeg | sed -n '1p')
[[ "$MASTER_FF" =~ ^[1-9][0-9]*$ ]]
MASTER_CMD=$(tr '\0' ' ' <"/proc/$MASTER_FF/cmdline")
[[ "$MASTER_CMD" == *'http://127.0.0.1:8789/overlay.mjpg'* ]]
[[ "$MASTER_CMD" == *'http://127.0.0.1:8788/overlay.mjpg'* ]]
[[ "$MASTER_CMD" == *'-r 30'* ]]
echo "MASTER_TICKER_WIRING=PASS"

# A source restart may briefly empty UDP input. Recover only the affected relay.
if ! rumble_connected; then systemctl restart "$RUMBLE"; sleep 6; fi
if ! youtube_connected; then systemctl restart "$COMP"; sleep 10; fi
active "$RUMBLE"; active "$COMP"; active "$ROUTING"
rumble_connected; youtube_connected

# Verify the master remains close to real-time after doubling RSS animation cadence.
sleep 8
PROGRESS=/srv/fgbears-live/logs/ffmpeg-progress.log
[[ -s "$PROGRESS" ]]
SPEED=$(awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); print v+0}' "$PROGRESS")
python3 - "$SPEED" <<'PY'
import sys
speed=float(sys.argv[1])
assert speed >= 0.96, speed
print(f'MASTER_REALTIME=PASS speed={speed:.3f}x')
PY

systemctl start fgbears-live-health.service
[[ "$(systemctl show -p Result --value fgbears-live-health.service)" == success ]]
rumble_connected
youtube_connected

echo "POST master=$MASTER1 rumble=$(mainpid "$RUMBLE") compositor=$(mainpid "$COMP") load=$(cut -d' ' -f1-3 /proc/loadavg)"
echo "RSS=30fps_boundary_swap_76pps"
echo "CRAWL=30fps_boundary_swap"
echo "STABLE_TICKERS=PASS"

SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/bears-news-feed-hq.py /tmp/crawl-overlay-hq.py /tmp/start-stream.sh /tmp/deploy-stable-tickers.sh

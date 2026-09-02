#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 77; }
MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
LEGACY=fgbears-youtube-relay.service
ENV=/etc/fgbears-live/stream.env
BACKUP=$(mktemp -d /srv/fgbears-live/runtime/ticker-deploy-backup.XXXXXX)
SUCCESS=0
BACKUP_READY=0

active() { systemctl is-active --quiet "$1"; }
mainpid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
connected_port() {
  local pid=$1 port=$2
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  ss -ntpH state established 2>/dev/null \
    | awk -v q="pid=$pid" -v p=":$port" 'index($0,q)&&index($0,p){ok=1} END{exit(ok?0:1)}'
}

restore_old() {
  local rc=${1:-1}
  trap - ERR EXIT
  if (( BACKUP_READY == 0 )); then
    rm -rf "$BACKUP"
    exit "$rc"
  fi
  echo "TICKER_ROLLBACK=BEGIN rc=$rc" >&2
  install -m 0755 "$BACKUP/crawl-overlay-hq.py" /opt/fgbears-live/bin/crawl-overlay-hq.py || true
  if [[ -f "$BACKUP/bears-news-feed-hq.py" ]]; then
    install -m 0755 "$BACKUP/bears-news-feed-hq.py" /opt/fgbears-live/bin/bears-news-feed-hq.py || true
  else
    rm -f /opt/fgbears-live/bin/bears-news-feed-hq.py || true
  fi
  install -m 0755 "$BACKUP/start-stream-opt.sh" /opt/fgbears-live/bin/start-stream.sh || true
  install -m 0755 "$BACKUP/fgbears-start-stream" /usr/local/bin/fgbears-start-stream || true
  cp -a "$BACKUP/stream.env" "$ENV" || true
  chown root:fgbears "$ENV" || true
  chmod 0640 "$ENV" || true
  systemctl reset-failed "$MASTER" || true
  systemctl restart "$MASTER" || true
  for _ in $(seq 1 45); do
    active "$MASTER" \
      && curl -fsS --max-time 2 http://127.0.0.1:8788/healthz >/dev/null 2>&1 \
      && curl -fsS --max-time 2 http://127.0.0.1:8789/healthz >/dev/null 2>&1 \
      && break
    sleep 1
  done
  echo "TICKER_ROLLBACK=COMPLETE" >&2
  exit "$rc"
}

# Preflight failures are read-only. Rollback is not armed until every previous
# production file has been captured successfully.
active "$MASTER"
active "$RUMBLE"
active "$COMP"
active "$ROUTING"
! active "$LEGACY"
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
COMP0=$(mainpid "$COMP")
ROUTING0=$(mainpid "$ROUTING")
[[ "$MASTER0" =~ ^[1-9][0-9]*$ ]]
[[ "$RUMBLE0" =~ ^[1-9][0-9]*$ ]]
[[ "$COMP0" =~ ^[1-9][0-9]*$ ]]
[[ "$ROUTING0" =~ ^[1-9][0-9]*$ ]]
connected_port "$RUMBLE0" 1935
connected_port "$COMP0" 443
echo "PRE master=$MASTER0 rumble=$RUMBLE0 youtube=$COMP0 routing=$ROUTING0 load=$(cut -d' ' -f1-3 /proc/loadavg)"

for f in /tmp/bears-news-feed-hq.py /tmp/crawl-overlay-hq.py /tmp/start-stream.sh; do
  [[ -s "$f" ]] || { echo "Missing staged ticker file: $f" >&2; exit 66; }
done

cp -a /opt/fgbears-live/bin/crawl-overlay-hq.py "$BACKUP/crawl-overlay-hq.py"
[[ ! -f /opt/fgbears-live/bin/bears-news-feed-hq.py ]] || cp -a /opt/fgbears-live/bin/bears-news-feed-hq.py "$BACKUP/bears-news-feed-hq.py"
cp -a /opt/fgbears-live/bin/start-stream.sh "$BACKUP/start-stream-opt.sh"
cp -a /usr/local/bin/fgbears-start-stream "$BACKUP/fgbears-start-stream"
cp -a "$ENV" "$BACKUP/stream.env"
BACKUP_READY=1
trap 'rc=$?; (( SUCCESS == 1 )) || restore_old "$rc"' EXIT

install -m 0755 /tmp/bears-news-feed-hq.py /opt/fgbears-live/bin/bears-news-feed-hq.py
install -m 0755 /tmp/crawl-overlay-hq.py /opt/fgbears-live/bin/crawl-overlay-hq.py
install -m 0755 /tmp/start-stream.sh /opt/fgbears-live/bin/start-stream.sh
install -m 0755 /tmp/start-stream.sh /usr/local/bin/fgbears-start-stream

python3 - "$ENV" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1])
lines=path.read_text(encoding='utf-8').splitlines()
updates={
 'OUTPUT_FPS':'30',
 'CRAWL_OVERLAY_SCRIPT':'/opt/fgbears-live/bin/crawl-overlay-hq.py',
 'CRAWL_OVERLAY_FPS':'30',
 'CRAWL_TEXT_RENDER_SCALE':'2',
 'BEARS_NEWS_SCRIPT':'/opt/fgbears-live/bin/bears-news-feed-hq.py',
 'BEARS_NEWS_OVERLAY_FPS':'30',
 'BEARS_NEWS_SCROLL_PPS':'76',
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
for key,val in updates.items():
    if key not in seen: out.append(f'{key}={val}')
path.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chown root:fgbears "$ENV"
chmod 0640 "$ENV"

python3 -m py_compile \
  /opt/fgbears-live/bin/bears-news-feed.py \
  /opt/fgbears-live/bin/bears-news-feed-hq.py \
  /opt/fgbears-live/bin/crawl-overlay.py \
  /opt/fgbears-live/bin/crawl-overlay-hq.py
bash -n /opt/fgbears-live/bin/start-stream.sh

# Exactly one intentional master restart loads both moving renderers. No
# destination service is restarted by this deployment or its success path.
systemctl reset-failed "$MASTER" || true
systemctl restart "$MASTER"

healthy=0
for _ in $(seq 1 45); do
  if active "$MASTER" \
    && curl -fsS --max-time 2 http://127.0.0.1:8788/healthz >/dev/null 2>&1 \
    && curl -fsS --max-time 2 http://127.0.0.1:8789/healthz >/dev/null 2>&1; then
    healthy=1; break
  fi
  sleep 1
done
(( healthy == 1 ))

RSS=$(curl -fsS --max-time 3 http://127.0.0.1:8789/healthz)
CRAWL=$(curl -fsS --max-time 3 http://127.0.0.1:8788/healthz)
printf '%s' "$RSS" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;assert p.get("scrollPps")==76,p;assert p.get("payloadSwap")=="next-cycle-boundary",p'
printf '%s' "$CRAWL" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;assert p.get("payloadSwap")=="next-segment-boundary",p'
echo "RSS_CONTRACT=PASS $RSS"
echo "CRAWL_CONTRACT=PASS $CRAWL"

active "$RUMBLE"
active "$COMP"
active "$ROUTING"
! active "$LEGACY"
[[ "$(mainpid "$RUMBLE")" == "$RUMBLE0" ]]
[[ "$(mainpid "$COMP")" == "$COMP0" ]]
[[ "$(mainpid "$ROUTING")" == "$ROUTING0" ]]
connected_port "$RUMBLE0" 1935
connected_port "$COMP0" 443
echo "DESTINATIONS_PRESERVED=PASS rumble=$RUMBLE0 youtube=$COMP0 routing=$ROUTING0"

PROGRESS=/srv/fgbears-live/logs/ffmpeg-progress.log
for _ in $(seq 1 20); do
  [[ -s "$PROGRESS" ]] && grep -q '^speed=' "$PROGRESS" && break
  sleep 1
done
[[ -s "$PROGRESS" ]]
SPEED=$(awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); print v+0}' "$PROGRESS")
python3 - "$SPEED" <<'PY'
import sys
s=float(sys.argv[1])
assert s >= 0.96, s
print(f'MASTER_REALTIME=PASS speed={s:.3f}x')
PY

MASTER1=$(mainpid "$MASTER")
[[ "$MASTER1" =~ ^[1-9][0-9]*$ && "$MASTER1" != "$MASTER0" ]]
echo "POST master=$MASTER1 rumble=$RUMBLE0 youtube=$COMP0 load=$(cut -d' ' -f1-3 /proc/loadavg)"
echo 'STABLE_TICKERS=PASS'
SUCCESS=1
trap - EXIT
rm -rf "$BACKUP" /tmp/bears-news-feed-hq.py /tmp/crawl-overlay-hq.py /tmp/start-stream.sh /tmp/deploy-stable-tickers.sh

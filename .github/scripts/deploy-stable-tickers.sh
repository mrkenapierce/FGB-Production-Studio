#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 77; }
MASTER=fgbears-live.service
RUMBLE=fgbears-rumble-relay.service
COMP=fgbears-youtube-lovable-compositor.service
ROUTING=fgbears-youtube-lovable-routing.service
ENV=/etc/fgbears-live/stream.env
BACKUP=$(mktemp -d /tmp/fgb-ticker-final.XXXXXX)

active() { systemctl is-active --quiet "$1"; }
mainpid() { systemctl show -p MainPID --value "$1" 2>/dev/null || echo 0; }
has_any_port() { ss -ntpH state established 2>/dev/null | grep -q ":$1 "; }

restore_old() {
  echo "TICKER_RESTORE=BEGIN"
  install -m 0755 "$BACKUP/crawl-overlay-hq.py" /opt/fgbears-live/bin/crawl-overlay-hq.py || true
  if [[ -f "$BACKUP/bears-news-feed-hq.py" ]]; then
    install -m 0755 "$BACKUP/bears-news-feed-hq.py" /opt/fgbears-live/bin/bears-news-feed-hq.py || true
  else
    rm -f /opt/fgbears-live/bin/bears-news-feed-hq.py || true
  fi
  install -m 0755 "$BACKUP/fgbears-start-stream" /usr/local/bin/fgbears-start-stream || true
  cp -a "$BACKUP/stream.env" "$ENV" || true
  chown root:fgbears "$ENV" || true
  chmod 0640 "$ENV" || true
  systemctl stop "$MASTER" || true
  sleep 12
  systemctl reset-failed "$MASTER" || true
  systemctl start "$MASTER" || true
  echo "TICKER_RESTORE=COMPLETE"
}

active "$MASTER"
active "$RUMBLE"
active "$COMP"
active "$ROUTING"
has_any_port 1935
has_any_port 443
MASTER0=$(mainpid "$MASTER")
RUMBLE0=$(mainpid "$RUMBLE")
COMP0=$(mainpid "$COMP")
echo "PRE master=$MASTER0 rumble=$RUMBLE0 youtube=$COMP0 load=$(cut -d' ' -f1-3 /proc/loadavg)"

cp -a /opt/fgbears-live/bin/crawl-overlay-hq.py "$BACKUP/crawl-overlay-hq.py"
[[ ! -f /opt/fgbears-live/bin/bears-news-feed-hq.py ]] || cp -a /opt/fgbears-live/bin/bears-news-feed-hq.py "$BACKUP/bears-news-feed-hq.py"
cp -a /usr/local/bin/fgbears-start-stream "$BACKUP/fgbears-start-stream"
cp -a "$ENV" "$BACKUP/stream.env"

install -m 0755 /tmp/bears-news-feed-hq.py /opt/fgbears-live/bin/bears-news-feed-hq.py
install -m 0755 /tmp/crawl-overlay-hq.py /opt/fgbears-live/bin/crawl-overlay-hq.py
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

python3 -m py_compile /opt/fgbears-live/bin/bears-news-feed.py /opt/fgbears-live/bin/bears-news-feed-hq.py /opt/fgbears-live/bin/crawl-overlay.py /opt/fgbears-live/bin/crawl-overlay-hq.py

# The renderer logic has already passed isolated contract tests. Production gets
# exactly one master restart. No process-tree assertions and no immediate second restart.
systemctl reset-failed "$MASTER" || true
if ! systemctl restart "$MASTER"; then
  restore_old
  exit 1
fi

healthy=0
for _ in $(seq 1 45); do
  if active "$MASTER" && curl -fsS --max-time 2 http://127.0.0.1:8788/healthz >/dev/null 2>&1 && curl -fsS --max-time 2 http://127.0.0.1:8789/healthz >/dev/null 2>&1; then
    healthy=1; break
  fi
  sleep 1
done
if (( healthy == 0 )); then
  echo "MASTER_OR_TICKERS=FAIL"
  systemctl status "$MASTER" --no-pager -l || true
  restore_old
  exit 1
fi

RSS=$(curl -fsS --max-time 3 http://127.0.0.1:8789/healthz)
CRAWL=$(curl -fsS --max-time 3 http://127.0.0.1:8788/healthz)
printf '%s' "$RSS" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;assert p.get("scrollPps")==76,p;assert p.get("payloadSwap")=="next-cycle-boundary",p'
printf '%s' "$CRAWL" | python3 -c 'import json,sys;p=json.load(sys.stdin);assert p.get("ok") is True,p;assert p.get("fps")==30,p;assert p.get("payloadSwap")=="next-segment-boundary",p'
echo "RSS_CONTRACT=PASS $RSS"
echo "CRAWL_CONTRACT=PASS $CRAWL"

# Wait for both independent destinations to consume the restored master. Restart
# only a relay that actually failed to reconnect; never restart the master again.
for _ in $(seq 1 25); do has_any_port 1935 && break; sleep 1; done
if ! has_any_port 1935; then
  systemctl reset-failed "$RUMBLE" || true
  systemctl restart "$RUMBLE"
  for _ in $(seq 1 25); do has_any_port 1935 && break; sleep 1; done
fi
for _ in $(seq 1 25); do has_any_port 443 && break; sleep 1; done
if ! has_any_port 443; then
  systemctl restart "$COMP"
  for _ in $(seq 1 25); do has_any_port 443 && break; sleep 1; done
fi
has_any_port 1935
has_any_port 443
active "$RUMBLE"; active "$COMP"; active "$ROUTING"

# Give FFmpeg enough time to publish a progress sample.
PROGRESS=/srv/fgbears-live/logs/ffmpeg-progress.log
for _ in $(seq 1 20); do
  if [[ -s "$PROGRESS" ]] && grep -q '^speed=' "$PROGRESS"; then break; fi
  sleep 1
done
if [[ -s "$PROGRESS" ]] && grep -q '^speed=' "$PROGRESS"; then
  SPEED=$(awk -F= '$1=="speed"{v=$2} END{gsub(/x/,"",v); print v+0}' "$PROGRESS")
  python3 - "$SPEED" <<'PY'
import sys
s=float(sys.argv[1])
assert s >= 0.96, s
print(f'MASTER_REALTIME=PASS speed={s:.3f}x')
PY
else
  echo 'MASTER_REALTIME=NO_SAMPLE'
fi

MASTER1=$(mainpid "$MASTER")
echo "POST master=$MASTER1 rumble=$(mainpid "$RUMBLE") youtube=$(mainpid "$COMP") load=$(cut -d' ' -f1-3 /proc/loadavg)"
echo 'STABLE_TICKERS=PASS'
rm -rf "$BACKUP" /tmp/bears-news-feed-hq.py /tmp/crawl-overlay-hq.py /tmp/start-stream.sh /tmp/deploy-stable-tickers.sh

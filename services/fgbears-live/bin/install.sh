#!/usr/bin/env bash
set -Eeuo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo bash install.sh" >&2; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
EXACT_CARD_PYLIB=/opt/fgbears-live/exact-card-pylib
QUARANTINE_BASE=/opt/fgbears-live/quarantine/retired-youtube

export DEBIAN_FRONTEND=noninteractive
required=(ffmpeg ca-certificates curl git jq rsync python3 python3-pil fonts-dejavu-core)
missing=()
for p in "${required[@]}"; do
  dpkg-query -W -f='${Status}\n' "$p" 2>/dev/null | grep -Fqx 'install ok installed' || missing+=("$p")
done
if ! PYTHONPATH="$EXACT_CARD_PYLIB" python3 -c 'import qrcode' >/dev/null 2>&1; then
  missing+=(python3-qrcode)
fi
if ((${#missing[@]})); then
  apt-get -o Acquire::Retries=3 update
  apt-get -o Acquire::Retries=3 install -y --no-install-recommends "${missing[@]}"
fi

id fgbears >/dev/null 2>&1 || useradd --system --home-dir /srv/fgbears-live --shell /usr/sbin/nologin fgbears
install -d -m0755 /opt/fgbears-live
# Quarantine and the isolated QR runtime are host state, not deployable source.
# Never let rsync --delete erase either directory.
rsync -a --delete --exclude 'exact-card-pylib/' --exclude 'quarantine/' "$SOURCE_DIR/" /opt/fgbears-live/

mv /opt/fgbears-live/bin/ad-overlay.py /opt/fgbears-live/bin/ad-overlay-base.py
install -m0755 /opt/fgbears-live/bin/ad-overlay-smart.py /opt/fgbears-live/bin/ad-overlay.py
install -d -m0755 /opt/fgbears-live/assets
base64 --decode "$SOURCE_DIR/../../renderer/assets/epic-logo-for-qr.base64.txt" > /opt/fgbears-live/assets/epic-logo.png
chmod 0644 /opt/fgbears-live/assets/epic-logo.png
install -m0644 "$SOURCE_DIR/assets/fgb-epic-default-interstitial.jpg" /opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg

install -d -o fgbears -g fgbears -m0755 /srv/fgbears-live /srv/fgbears-live/media /srv/fgbears-live/incoming /srv/fgbears-live/logs /srv/fgbears-live/runtime
install -d -o root -g root -m0755 /srv/fgbears-live/health
install -d -o root -g fgbears -m0750 /etc/fgbears-live
install -d -m0750 "$QUARANTINE_BASE"

# Supported stream topology: exactly three owners.
install -m0755 /opt/fgbears-live/bin/start-stream.sh /usr/local/bin/fgbears-start-stream
install -m0755 /opt/fgbears-live/bin/rumble-relay.sh /usr/local/bin/fgbears-rumble-relay
install -m0644 /opt/fgbears-live/systemd/fgbears-live.service /etc/systemd/system/fgbears-live.service
install -m0644 /opt/fgbears-live/systemd/fgbears-rumble-relay.service /etc/systemd/system/fgbears-rumble-relay.service
install -m0644 /opt/fgbears-live/systemd/fgbears-youtube-output.service /etc/systemd/system/fgbears-youtube-output.service

# Shared-master health only. The current YouTube service owns its own systemd
# Restart policy; no second router/watchdog/fallback owner is permitted.
install -m0755 /opt/fgbears-live/bin/healthcheck.sh /usr/local/bin/fgbears-healthcheck
install -m0644 /opt/fgbears-live/systemd/fgbears-live-health.service /etc/systemd/system/fgbears-live-health.service
install -m0644 /opt/fgbears-live/systemd/fgbears-live-health.timer /etc/systemd/system/fgbears-live-health.timer

for spec in \
  'normalize-library.sh:fgbears-normalize' \
  'validate-media.sh:fgbears-validate' \
  'rebuild-playlist.sh:fgbears-rebuild-playlist' \
  'add-episode.sh:fgbears-add-episode' \
  'audio-health.py:fgbears-audio-health' \
  'stream-status.sh:fgbears-stream-status' \
  'configure-rumble.sh:fgbears-configure-rumble'; do
  src=${spec%%:*}; dst=${spec##*:}
  install -m0755 "/opt/fgbears-live/bin/$src" "/usr/local/bin/$dst"
done

ENV_PATH=/etc/fgbears-live/stream.env
[[ -e "$ENV_PATH" ]] || install -o root -g fgbears -m0640 /opt/fgbears-live/config/stream.env.example "$ENV_PATH"
python3 - "$ENV_PATH" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); lines=p.read_text(encoding='utf-8').splitlines(); vals={}
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        k,v=line.split('=',1); vals[k]=v
upstream=vals.get('YOUTUBE_UPSTREAM_RTMP_BASE') or vals.get('YOUTUBE_RTMP_BASE') or 'rtmps://a.rtmps.youtube.com/live2'
if upstream.startswith('rtmp://127.0.0.1:'): upstream='rtmps://a.rtmps.youtube.com/live2'
updates={
 'YOUTUBE_LOCAL_UDP_URL':'udp://127.0.0.1:1939?pkt_size=1316', 'YOUTUBE_UPSTREAM_RTMP_BASE':upstream,
 'RUMBLE_LOCAL_UDP_URL':'udp://127.0.0.1:1940?pkt_size=1316', 'RUMBLE_UPSTREAM_RTMP_BASE':'rtmp://rtmp.rumble.com/live',
 'OUTPUT_FPS':'30','AD_OVERLAY_FPS':'15','CRAWL_OVERLAY_FPS':'30','CRAWL_OVERLAY_SCRIPT':'/opt/fgbears-live/bin/crawl-overlay-hq.py',
 'BEARS_NEWS_SCRIPT':'/opt/fgbears-live/bin/bears-news-feed-hq.py','BEARS_NEWS_OVERLAY_PORT':'8789','BEARS_NEWS_OVERLAY_FPS':'30','BEARS_NEWS_SCROLL_PPS':'76',
}
retired={'YOUTUBE_RTMP_BASE','YOUTUBE_AUDIO_BITRATE','YOUTUBE_AUDIO_SAMPLE_RATE','YOUTUBE_AUDIO_CHANNELS','YOUTUBE_VIDEO_BITRATE','YOUTUBE_VIDEO_MAXRATE','YOUTUBE_VIDEO_BUFSIZE','FGB_YOUTUBE_PACKET_ROUTER_ENABLE'}
out=[]; seen=set()
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        k=line.split('=',1)[0]
        if k in retired or k.startswith(('YOUTUBE_TRIVIA_','FGB_YOUTUBE_TRIVIA_')): continue
        if k in updates:
            if k not in seen: out.append(f'{k}={updates[k]}'); seen.add(k)
            continue
    out.append(line)
for k,v in updates.items():
    if k not in seen: out.append(f'{k}={v}')
p.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chown root:fgbears "$ENV_PATH"; chmod 0640 "$ENV_PATH"

# Quarantine is a persistent safety boundary, not a one-time cleanup. Anything
# from a retired YouTube architecture that reappears in a deploy is archived out
# of executable paths and its unit name is hard-masked to /dev/null.
retired_units=(
  fgbears-youtube-relay.service fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service
  fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer
)
retired_files=(
  /usr/local/bin/fgbears-youtube-relay /usr/local/bin/fgbears-youtube-audio-watchdog
  /opt/fgbears-live/bin/youtube-lovable-compositor.sh /opt/fgbears-live/bin/youtube-question-mask.py
  /opt/fgbears-live/bin/youtube-transport-watchdog.sh /opt/fgbears-live/bin/youtube-audio-watchdog-owner-aware.sh
  /opt/fgbears-live/bin/youtube-relay.sh /opt/fgbears-live/bin/youtube-relay-legacy.sh
  /opt/fgbears-live/bin/youtube-stream-router.py /opt/fgbears-live/bin/youtube-stream-router-v5.py
  /opt/fgbears-live/bin/youtube-compositor-source-relay.sh /opt/fgbears-live/bin/finalize-youtube-only.py
)
stamp=$(date -u +%Y%m%dT%H%M%SZ); q="$QUARANTINE_BASE/$stamp-install"; install -d -m0750 "$q/bin" "$q/systemd" "$q/usr-local-bin"
for u in "${retired_units[@]}"; do
  systemctl stop "$u" >/dev/null 2>&1 || true; systemctl disable "$u" >/dev/null 2>&1 || true
  unit="/etc/systemd/system/$u"
  [[ -e "$unit" && ! -L "$unit" ]] && mv "$unit" "$q/systemd/$u" || true
  rm -f "$unit"; ln -s /dev/null "$unit"
  src="/opt/fgbears-live/systemd/$u"; [[ -e "$src" ]] && mv "$src" "$q/systemd/source-$u" || true
done
for f in "${retired_files[@]}"; do
  [[ -e "$f" || -L "$f" ]] || continue
  if [[ "$f" == /usr/local/bin/* ]]; then d="$q/usr-local-bin"; else d="$q/bin"; fi
  mv "$f" "$d/$(basename "$f")"
done
rm -f /usr/local/libexec/fgbears-youtube-audio-watchdog-legacy
chmod -R a-w "$q"

systemctl daemon-reload
systemctl enable fgbears-live.service fgbears-rumble-relay.service fgbears-youtube-output.service
systemctl enable --now fgbears-live-health.timer

echo 'Installed minimal FGBears topology with retired YouTube pathways persistently quarantined.'

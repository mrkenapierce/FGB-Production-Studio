#!/usr/bin/env python3
from pathlib import Path
import re
import shutil
import textwrap

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "services/fgbears-live"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def move_if_exists(src_rel: str, dst_rel: str) -> None:
    src = ROOT / src_rel
    if not src.exists():
        return
    dst = ROOT / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    shutil.move(str(src), str(dst))


# 1) Master encoder: one local output, Rumble only.
path = "services/fgbears-live/bin/start-stream.sh"
text = read(path)
text = re.sub(r'^: "\$\{YOUTUBE_STREAM_KEY.*\n', '', text, flags=re.M)
text = re.sub(r'^: "\$\{YOUTUBE_LOCAL_UDP_URL.*\n', '', text, flags=re.M)
text = re.sub(
    r'\[\[ "\$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" \]\] \|\| \{\n.*?\n\}\n',
    '', text, flags=re.S,
)
text = re.sub(
    r'\[\[ "\$YOUTUBE_LOCAL_UDP_URL" == udp://127\.0\.0\.1:\* \]\] \|\| \{\n.*?\n\}\n',
    '', text, flags=re.S,
)
text = re.sub(
    r'TEE_TARGETS="\[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore\]\$\{YOUTUBE_LOCAL_UDP_URL\}\|\[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore\]\$\{RUMBLE_LOCAL_UDP_URL\}"',
    'TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${RUMBLE_LOCAL_UDP_URL}"',
    text,
)
text = text.replace(
    "printf 'FGBears Live output: isolated YouTube and Rumble local UDP mirrors.\\n'",
    "printf 'FGBears Live output: Rumble local UDP mirror only.\\n'",
)
if "YOUTUBE_" in text or "udp://127.0.0.1:1939" in text:
    raise SystemExit("start-stream.sh still contains YouTube transport")
if "RUMBLE_LOCAL_UDP_URL" not in text:
    raise SystemExit("Rumble local UDP target missing")
write(path, text)

# 2) Audio health: observe the exact Rumble-bound MPEG-TS signal.
path = "services/fgbears-live/bin/audio-health.py"
text = read(path)
text = text.replace(
    '"""Objective health check for the exact YouTube-bound FGB audio transport."""',
    '"""Objective health check for the exact Rumble-bound FGB audio transport."""',
)
text = text.replace('prefix = "YOUTUBE_LOCAL_UDP_URL=udp://127.0.0.1:"', 'prefix = "RUMBLE_LOCAL_UDP_URL=udp://127.0.0.1:"')
text = text.replace('return 1939', 'return 1940')
text = text.replace('REASON=INSUFFICIENT_YOUTUBE_BOUND_PACKETS', 'REASON=INSUFFICIENT_RUMBLE_BOUND_PACKETS')
if "YOUTUBE_LOCAL_UDP_URL" in text or "return 1939" in text:
    raise SystemExit("audio-health.py still points at YouTube")
write(path, text)

# 3) Health supervision: master + Rumble only; retain lag/audio/news checks.
path = "services/fgbears-live/bin/healthcheck.sh"
text = read(path)
text = re.sub(
    r'# YouTube desired generation.*?^YOUTUBE_WARNING_FILE=.*\n',
    'RUMBLE_SERVICE=${RUMBLE_SERVICE:-fgbears-rumble-relay.service}\n',
    text,
    flags=re.S | re.M,
)
replacement = r'''
recover_rumble_destination() {
  if systemctl is-active --quiet "$RUMBLE_SERVICE"; then return 0; fi
  logger -t fgbears-live-health "Rumble relay is inactive; restarting only the Rumble destination process."
  systemctl reset-failed "$RUMBLE_SERVICE" || true
  systemctl restart "$RUMBLE_SERVICE" || true
  for _ in {1..20}; do
    if systemctl is-active --quiet "$RUMBLE_SERVICE"; then
      logger -t fgbears-live-health "RUMBLE_RECOVERY=RECOVERED service=$RUMBLE_SERVICE"
      return 0
    fi
    sleep 0.25
  done
  logger -t fgbears-live-health "RUMBLE_RECOVERY=FAILED service=$RUMBLE_SERVICE"
  return 1
}

run_lag_check() {
'''
text = re.sub(r'\nyoutube_generation\(\) \{.*?\nrun_lag_check\(\) \{\n', '\n' + replacement, text, flags=re.S)
text = re.sub(
    r'run_news_refresh\n\[\[ -r "\$ENV_FILE" && -s "\$PLAYLIST_FILE" \]\] \|\| exit 0\n.*?\nif ! systemctl is-active --quiet fgbears-live\.service; then',
    '''run_news_refresh
[[ -r "$ENV_FILE" && -s "$PLAYLIST_FILE" ]] || exit 0
if grep -q '^RUMBLE_STREAM_KEY=REPLACE_WITH_RUMBLE_STREAM_KEY$' "$ENV_FILE"; then exit 0; fi

recover_rumble_destination || true

if ! systemctl is-active --quiet fgbears-live.service; then''',
    text,
    flags=re.S,
)
for forbidden in ("YOUTUBE_", "youtube_generation", "recover_youtube", "check_youtube"):
    if forbidden in text:
        raise SystemExit(f"healthcheck still contains retired marker: {forbidden}")
write(path, text)

# 4) Rumble-only configuration template.
write("services/fgbears-live/config/stream.env.example", textwrap.dedent(r'''\
# FGBears production stream configuration template.
# Copy to /etc/fgbears-live/stream.env and protect the live stream key.

# One authoritative transport: Oracle master -> local MPEG-TS -> Rumble relay.
RUMBLE_STREAM_KEY=REPLACE_WITH_RUMBLE_STREAM_KEY
RUMBLE_LOCAL_UDP_URL=udp://127.0.0.1:1940?pkt_size=1316
RUMBLE_UPSTREAM_RTMP_BASE=rtmp://rtmp.rumble.com/live

RUMBLE_TRIVIA_URL=https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html
RUMBLE_TRIVIA_DISPLAY_URL=rumble.com/v7eqrsu

PLAYLIST_FILE=/srv/fgbears-live/playlist.ffconcat
FFMPEG_LOGLEVEL=warning
OUTPUT_FPS=30
VIDEO_GOP=60

AD_OVERLAY_PORT=8787
AD_OVERLAY_FPS=15
AD_OVERLAY_SCRIPT=/opt/fgbears-live/bin/ad-overlay.py
CRAWL_OVERLAY_PORT=8788
CRAWL_OVERLAY_FPS=30
CRAWL_OVERLAY_SCRIPT=/opt/fgbears-live/bin/crawl-overlay-hq.py
CRAWL_TEXT_RENDER_SCALE=2
BEARS_NEWS_SCRIPT=/opt/fgbears-live/bin/bears-news-feed.py
BEARS_NEWS_OVERLAY_PORT=8789
BEARS_NEWS_OVERLAY_FPS=30
BEARS_NEWS_SCROLL_PPS=58

FFMPEG_PROGRESS_FILE=/srv/fgbears-live/logs/ffmpeg-progress.log
'''))

# 5) Installer: remove destination-specific YouTube implementation and make
#    every reinstall converge on Rumble-only runtime state.
path = "services/fgbears-live/bin/install.sh"
text = read(path)
marker = "# YouTube v3 is the only authorized destination-specific media implementation."
if marker not in text:
    raise SystemExit("install.sh YouTube v3 marker not found")
prefix = text.split(marker, 1)[0]
install_tail = r'''ENV_PATH=/etc/fgbears-live/stream.env
if [[ ! -e "$ENV_PATH" ]]; then
  install -o root -g fgbears -m 0640 /opt/fgbears-live/config/stream.env.example "$ENV_PATH"
fi
python3 - "$ENV_PATH" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1])
lines=path.read_text(encoding='utf-8').splitlines()
updates={
    'RUMBLE_LOCAL_UDP_URL':'udp://127.0.0.1:1940?pkt_size=1316',
    'RUMBLE_UPSTREAM_RTMP_BASE':'rtmp://rtmp.rumble.com/live',
    'RUMBLE_TRIVIA_URL':'https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html',
    'RUMBLE_TRIVIA_DISPLAY_URL':'rumble.com/v7eqrsu',
    'OUTPUT_FPS':'30','AD_OVERLAY_FPS':'15','CRAWL_OVERLAY_FPS':'30',
    'CRAWL_OVERLAY_SCRIPT':'/opt/fgbears-live/bin/crawl-overlay-hq.py','CRAWL_TEXT_RENDER_SCALE':'2',
    'BEARS_NEWS_SCRIPT':'/opt/fgbears-live/bin/bears-news-feed.py',
    'BEARS_NEWS_OVERLAY_PORT':'8789','BEARS_NEWS_OVERLAY_FPS':'30','BEARS_NEWS_SCROLL_PPS':'58',
}
retired_prefixes=('YOUTUBE_','FGB_YOUTUBE_','RUMBLE_STUDIO_','X_','INSTAGRAM_','FACEBOOK_')
retired_exact={'PODCAST_AUDIO_FILTER'}
seen=set(); out=[]
for line in lines:
    if '=' in line and not line.lstrip().startswith('#'):
        key=line.split('=',1)[0]
        if key.startswith(retired_prefixes) or key in retired_exact:
            continue
        if key in updates:
            if key not in seen:
                out.append(f'{key}={updates[key]}'); seen.add(key)
            continue
    out.append(line)
for key,value in updates.items():
    if key not in seen: out.append(f'{key}={value}')
if not any(line.startswith('RUMBLE_STREAM_KEY=') for line in out):
    out.append('RUMBLE_STREAM_KEY=REPLACE_WITH_RUMBLE_STREAM_KEY')
path.write_text('\n'.join(out)+'\n',encoding='utf-8')
PY
chown root:fgbears "$ENV_PATH"; chmod 0640 "$ENV_PATH"

# Remove and permanently mask every retired destination-specific runtime.
retired_units=(
  fgbears-youtube-v3.service
  fgbears-lovable-state-cache.service
  fgbears-youtube-v2.service
  fgbears-youtube-output.service
  fgbears-youtube-relay.service
  fgbears-youtube-router.service
  fgbears-youtube-lovable-routing.service
  fgbears-youtube-lovable-compositor.service
  fgbears-youtube-audio-watchdog.service
  fgbears-youtube-audio-watchdog.timer
  fgbears-rumble-studio-uplink.service
)
for unit in "${retired_units[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$unit" "/lib/systemd/system/$unit" "/usr/lib/systemd/system/$unit"
done
rm -rf /opt/fgbears-live/youtube-v3 /run/fgbears-youtube-v3 /run/fgbears-control-plane
rm -f /usr/local/bin/fgbears-youtube-* /usr/local/bin/fgbears-rumble-studio* /usr/local/bin/fgbears-lovable-state-cache
systemctl daemon-reload
for unit in "${retired_units[@]}"; do systemctl mask "$unit" >/dev/null 2>&1 || true; done

systemctl enable fgbears-live.service fgbears-rumble-relay.service >/dev/null
systemctl enable --now fgbears-live-health.timer

echo "Installed FGBears Live in Rumble-only mode. Live transport was not restarted by installer."
'''
text = prefix + install_tail
if "youtube-v3" in text.lower() and "retired_units" not in text:
    raise SystemExit("unexpected YouTube installer content")
write(path, text)

# 6) Architecture test: exactly one master transport and copy-only Rumble relay.
write("services/fgbears-live/tests/test-multistream.sh", textwrap.dedent(r'''\
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/rumble-relay.sh" "$ROOT/bin/configure-rumble.sh" "$ROOT/bin/install.sh" "$ROOT/bin/healthcheck.sh" "$ROOT/bin/stream-status.sh"; do bash -n "$script"; done
python3 "$ROOT/bin/audio-health.py" --self-test

grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
grep -Fq 'RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940' "$ROOT/bin/start-stream.sh"
grep -Fq 'Rumble local UDP mirror only' "$ROOT/bin/start-stream.sh"
! grep -Eq 'YOUTUBE_|127\.0\.0\.1:1939|127\.0\.0\.1:1941' "$ROOT/bin/start-stream.sh"
if [[ $(grep -Fc -- '-c:v libx264' "$ROOT/bin/start-stream.sh") -ne 1 ]]; then echo 'Master must contain exactly one video encode.' >&2; exit 1; fi

grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
! grep -Eq 'libx264|libx265|overlay=|studio-rtmp|youtube' "$ROOT/bin/rumble-relay.sh"
! test -d "$ROOT/youtube-v3"
! test -e "$ROOT/bin/rumble-studio-relay.sh"

ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=size=160x90:rate=10:duration=1 -f lavfi -i sine=frequency=440:sample_rate=48000:duration=1 -map 0:v:0 -map 1:a:0 -c:v libx264 -preset ultrafast -g 20 -c:a aac -f tee -use_fifo 1 "[f=mpegts]$TMP/rumble-local.ts"
test -s "$TMP/rumble-local.ts"
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/rumble-local.ts" | grep -q '^codec_name=h264$'
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/rumble-local.ts" | grep -q '^codec_name=aac$'

echo 'Rumble-only architecture passed: one master encode, one local Rumble handoff, one copy/remux relay.'
'''))

# 7) Future production deployment workflow: converge Oracle to Rumble only and
#    verify signal, socket, pace and audio instead of only process liveness.
write(".github/workflows/fgbears-live-deploy.yml", textwrap.dedent(r'''\
name: Deploy FGBears Rumble-Only Program

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'services/fgbears-live/**'

permissions:
  contents: read

concurrency:
  group: fgbears-rumble-only-production-deploy
  cancel-in-progress: false

env:
  ORACLE_USER: ubuntu

jobs:
  deploy:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - name: Validate Rumble-only source
        run: |
          set -Eeuo pipefail
          bash services/fgbears-live/tests/test-multistream.sh
          ! grep -R -nE 'YOUTUBE_LOCAL_UDP_URL|RUMBLE_STUDIO_ENABLE|studio-rtmp\.rumble\.com' services/fgbears-live/bin services/fgbears-live/config services/fgbears-live/systemd

      - name: Configure Oracle SSH
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
          ORACLE_SSH_KEY: ${{ secrets.ORACLE_SSH_KEY }}
        run: |
          set -Eeuo pipefail
          test -n "$ORACLE_HOST"; test -n "$ORACLE_SSH_KEY"
          install -d -m 700 ~/.ssh
          printf '%s\n' "$ORACLE_SSH_KEY" > ~/.ssh/oracle_key
          chmod 600 ~/.ssh/oracle_key
          ssh-keyscan -H "$ORACLE_HOST" >> ~/.ssh/known_hosts

      - name: Cut Oracle over to one Rumble transport
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
        run: |
          set -Eeuo pipefail
          rm -rf /tmp/fgbears-rumble-only
          git clone --depth 1 https://github.com/${{ github.repository }}.git /tmp/fgbears-rumble-only
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo systemctl stop fgbears-live-health.timer >/dev/null 2>&1 || true'
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo systemctl disable --now fgbears-youtube-v3.service fgbears-lovable-state-cache.service fgbears-youtube-v2.service fgbears-youtube-output.service fgbears-youtube-relay.service fgbears-youtube-router.service fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer fgbears-rumble-studio-uplink.service >/dev/null 2>&1 || true'
          scp -i ~/.ssh/oracle_key -r /tmp/fgbears-rumble-only "$ORACLE_USER@$ORACLE_HOST:/tmp/fgbears-rumble-only-stage"
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo bash /tmp/fgbears-rumble-only-stage/services/fgbears-live/bin/install.sh'
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo systemctl restart fgbears-live.service && sudo systemctl restart fgbears-rumble-relay.service && sudo systemctl enable --now fgbears-live-health.timer'

      - name: Verify Rumble-only runtime and media health
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
        run: |
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'bash -s' <<'REMOTE'
          set -Eeuo pipefail
          MASTER=fgbears-live.service
          RUMBLE=fgbears-rumble-relay.service
          systemctl is-active --quiet "$MASTER"
          systemctl is-active --quiet "$RUMBLE"
          service_pid=$(systemctl show -p MainPID --value "$MASTER")
          ffmpeg_pid=$(pgrep -P "$service_pid" -x ffmpeg | head -n1)
          [[ "$ffmpeg_pid" =~ ^[1-9][0-9]*$ ]]
          cmd=$(sudo tr '\0' ' ' < "/proc/$ffmpeg_pid/cmdline")
          grep -Fq 'udp://127.0.0.1:1940?pkt_size=1316' <<<"$cmd"
          ! grep -Eq '127\.0\.0\.1:1939|127\.0\.0\.1:1941|youtube' <<<"${cmd,,}"
          ! sudo grep -Eq '^(YOUTUBE_|FGB_YOUTUBE_|RUMBLE_STUDIO_)' /etc/fgbears-live/stream.env

          retired=(fgbears-youtube-v3.service fgbears-lovable-state-cache.service fgbears-youtube-v2.service fgbears-youtube-output.service fgbears-youtube-relay.service fgbears-youtube-router.service fgbears-youtube-lovable-routing.service fgbears-youtube-lovable-compositor.service fgbears-youtube-audio-watchdog.service fgbears-youtube-audio-watchdog.timer fgbears-rumble-studio-uplink.service)
          for unit in "${retired[@]}"; do
            ! systemctl is-active --quiet "$unit" || { echo "RETIRED_UNIT_ACTIVE=$unit" >&2; exit 1; }
          done

          relay_pid=$(systemctl show -p MainPID --value "$RUMBLE")
          [[ "$relay_pid" =~ ^[1-9][0-9]*$ ]]
          getent ahostsv4 rtmp.rumble.com | awk '{print $1}' | sort -u >/tmp/rumble-ips
          sudo ss -ntpH state established | grep "pid=$relay_pid" >/tmp/rumble-sockets || true
          socket_count=0
          while read -r ip; do
            [[ -n "$ip" ]] || continue
            n=$(grep -Fc "$ip:1935" /tmp/rumble-sockets || true)
            socket_count=$((socket_count+n))
          done </tmp/rumble-ips
          test "$socket_count" -eq 1 || { echo "RUMBLE_RTMP_SOCKET_COUNT=$socket_count" >&2; cat /tmp/rumble-sockets >&2; exit 1; }

          progress=/srv/fgbears-live/logs/ffmpeg-progress.log
          media(){ sudo sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$progress" | tail -n1; }
          m0=$(media); t0=$(date +%s%N); sleep 12; m1=$(media); t1=$(date +%s%N)
          rate=$(python3 - "$m0" "$m1" "$t0" "$t1" <<'PY'
          import sys
          m0,m1,t0,t1=map(int,sys.argv[1:]); print(f'{((m1-m0)/1e6)/((t1-t0)/1e9):.4f}')
          PY
          )
          python3 - "$rate" <<'PY'
          import sys
          assert float(sys.argv[1]) >= 0.95, sys.argv[1]
          PY

          sudo /usr/local/bin/fgbears-audio-health --capture-seconds 8
          cpu=$(ps -p "$ffmpeg_pid" -o pcpu= | xargs)
          echo "RUMBLE_ONLY_CUTOVER=PASS master_pid=$ffmpeg_pid relay_pid=$relay_pid rtmp_sockets=$socket_count interval_speed=${rate}x master_cpu_pct=${cpu:-NA}"
          REMOTE
'''))

# 8) Manual Rumble activation/recovery workflow has no YouTube assumptions.
write(".github/workflows/activate-fgb-rumble.yml", textwrap.dedent(r'''\
name: Activate FGBears Direct Rumble Relay
on: { workflow_dispatch: {} }
permissions: { contents: read }
concurrency:
  group: fgbears-rumble-production-activation
  cancel-in-progress: false
env: { ORACLE_USER: ubuntu }
jobs:
  activate:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Configure SSH
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
          ORACLE_SSH_KEY: ${{ secrets.ORACLE_SSH_KEY }}
        run: |
          test -n "$ORACLE_HOST"; test -n "$ORACLE_SSH_KEY"
          install -d -m 700 ~/.ssh
          printf '%s\n' "$ORACLE_SSH_KEY" > ~/.ssh/oracle_key
          chmod 600 ~/.ssh/oracle_key
          ssh-keyscan -H "$ORACLE_HOST" >> ~/.ssh/known_hosts
      - name: Install key and verify one direct Rumble socket
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
          RUMBLE_STREAM_KEY: ${{ secrets.RUMBLE_STREAM_KEY }}
        run: |
          test -n "$RUMBLE_STREAM_KEY"
          printf '%s\n' "$RUMBLE_STREAM_KEY" | ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'sudo /usr/local/bin/fgbears-configure-rumble'
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'bash -s' <<'REMOTE'
          set -Eeuo pipefail
          systemctl is-active --quiet fgbears-live.service
          systemctl is-active --quiet fgbears-rumble-relay.service
          pid=$(systemctl show -p MainPID --value fgbears-rumble-relay.service)
          getent ahostsv4 rtmp.rumble.com | awk '{print $1}' | sort -u >/tmp/ips
          sudo ss -ntpH state established | grep "pid=$pid" >/tmp/socks || true
          n=0; while read -r ip; do n=$((n+$(grep -Fc "$ip:1935" /tmp/socks || true))); done </tmp/ips
          test "$n" -eq 1
          ! sudo grep -Eq '^(YOUTUBE_|FGB_YOUTUBE_|RUMBLE_STUDIO_)' /etc/fgbears-live/stream.env
          echo "DIRECT_RUMBLE=PASS relay_pid=$pid rtmp_sockets=$n"
          REMOTE
'''))

# 9) Scheduled monitor now measures the actual Rumble-bound system.
write(".github/workflows/fgbears-live-monitor.yml", textwrap.dedent(r'''\
name: Monitor FGBears Rumble Live
on:
  schedule:
    - cron: '*/15 * * * *'
  workflow_dispatch:
permissions: { contents: read }
concurrency:
  group: fgbears-rumble-live-monitor
  cancel-in-progress: true
env: { ORACLE_USER: ubuntu }
jobs:
  monitor:
    runs-on: ubuntu-latest
    timeout-minutes: 4
    steps:
      - name: Configure SSH
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
          ORACLE_SSH_KEY: ${{ secrets.ORACLE_SSH_KEY }}
        run: |
          test -n "$ORACLE_HOST"; test -n "$ORACLE_SSH_KEY"
          install -d -m 700 ~/.ssh
          printf '%s\n' "$ORACLE_SSH_KEY" > ~/.ssh/oracle_key
          chmod 600 ~/.ssh/oracle_key
          ssh-keyscan -H "$ORACLE_HOST" >> ~/.ssh/known_hosts
      - name: Read-only Rumble transport check
        env:
          ORACLE_HOST: ${{ secrets.ORACLE_HOST }}
        run: |
          ssh -i ~/.ssh/oracle_key "$ORACLE_USER@$ORACLE_HOST" 'bash -s' <<'REMOTE'
          set -Eeuo pipefail
          systemctl is-active --quiet fgbears-live.service
          systemctl is-active --quiet fgbears-rumble-relay.service
          pid=$(systemctl show -p MainPID --value fgbears-live.service)
          ff=$(pgrep -P "$pid" -x ffmpeg | head -n1); [[ "$ff" =~ ^[1-9][0-9]*$ ]]
          cmd=$(sudo tr '\0' ' ' < "/proc/$ff/cmdline")
          grep -Fq '127.0.0.1:1940' <<<"$cmd"; ! grep -Fq '127.0.0.1:1939' <<<"$cmd"
          relay=$(systemctl show -p MainPID --value fgbears-rumble-relay.service)
          getent ahostsv4 rtmp.rumble.com | awk '{print $1}' | sort -u >/tmp/ips
          sudo ss -ntpH state established | grep "pid=$relay" >/tmp/socks || true
          n=0; while read -r ip; do n=$((n+$(grep -Fc "$ip:1935" /tmp/socks || true))); done </tmp/ips
          test "$n" -eq 1
          progress=/srv/fgbears-live/logs/ffmpeg-progress.log
          media(){ sudo sed -n 's/^out_time_us=\([0-9]*\)$/\1/p' "$progress" | tail -n1; }
          a=$(media); t=$(date +%s%N); sleep 10; b=$(media); u=$(date +%s%N)
          rate=$(python3 - "$a" "$b" "$t" "$u" <<'PY'
          import sys
          a,b,t,u=map(int,sys.argv[1:]); print(f'{((b-a)/1e6)/((u-t)/1e9):.4f}')
          PY
          )
          python3 - "$rate" <<'PY'
          import sys; assert float(sys.argv[1]) >= 0.95, sys.argv[1]
          PY
          echo "RUMBLE_MONITOR=OK master_pid=$ff relay_pid=$relay rtmp_sockets=$n interval_speed=${rate}x"
          REMOTE
'''))

# 10) Quarantine all active Studio transport pilots and the one-shot migration
#     workflow after it has started. Preserve them for audit, never execution.
studio_workflows = [
    "activate-rumble-studio-shadow.yml",
    "deploy-rumble-studio-isolated-uplink.yml",
    "rumble-studio-pilot.yml",
    "rumble-studio-readonly-diag.yml",
    "restore-rumble-direct.yml",
]
for name in studio_workflows:
    move_if_exists(f".github/workflows/{name}", f".github/quarantine/rumble-studio-retired-2026-09-03/workflows/{name}.disabled")
for name in ("decommission-fgb-social-sidecars.yml", "decommission-fgb-social-source-v2.yml"):
    move_if_exists(f".github/workflows/{name}", f".github/quarantine/legacy-routing-retired-2026-09-03/workflows/{name}.disabled")
move_if_exists(".github/workflows/canonicalize-fgb-rumble-only.yml", ".github/quarantine/rumble-only-cutover-2026-09-03/canonicalize-fgb-rumble-only.yml.disabled")
move_if_exists("services/fgbears-live/youtube-v3", "services/fgbears-live/quarantine/youtube-v3-retired-20260903")
move_if_exists("services/fgbears-live/bin/youtube-broadcast-control.py", "services/fgbears-live/quarantine/youtube-v3-retired-20260903/bin/youtube-broadcast-control.py")
move_if_exists("services/fgbears-live/bin/rumble-studio-relay.sh", "services/fgbears-live/quarantine/rumble-studio-retired-20260903/bin/rumble-studio-relay.sh")
move_if_exists("pilots/rumble-studio", "quarantine/rumble-studio-retired-20260903/pilot")

# Make all quarantine payloads non-executable in git working tree where mode
# is visible to tests/packaging. Contents remain for audit/history.
for qroot in (ROOT / ".github/quarantine", LIVE / "quarantine", ROOT / "quarantine"):
    if qroot.exists():
        for item in qroot.rglob("*"):
            if item.is_file():
                item.chmod(0o644)

print("CANONICAL_RUMBLE_ONLY=PASS")

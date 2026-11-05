#!/usr/bin/env bash
# CNT (CruiseNewsTrivia) capture ONLY. Independent of every FGB output:
# renders /channels/cruisenewstrivia/broadcast, sends ONE RTMP(S) stream to the
# CNT YouTube ingest, no shared secrets.
set -uo pipefail
umask 077
source ./cnt-lifecycle.sh

: "${BROADCAST_ORIGIN:?BROADCAST_ORIGIN required}"
: "${CNT_YOUTUBE_INGEST_URL:?CNT_YOUTUBE_INGEST_URL required}"
: "${CNT_YOUTUBE_STREAM_KEY:?CNT_YOUTUBE_STREAM_KEY required}"
CNT_DEST="${CNT_YOUTUBE_INGEST_URL%/}/${CNT_YOUTUBE_STREAM_KEY}"   # never logged
URL="${BROADCAST_ORIGIN%/}/channels/cruisenewstrivia/broadcast"
VIDEO_BITRATE="${CNT_VIDEO_BITRATE:-6000k}"
AUDIO_BITRATE="${CNT_AUDIO_BITRATE:-160k}"
STALL_SECONDS="${CNT_STALL_SECONDS:-20}"
PROGRESS=/tmp/cnt-ffmpeg.progress
export DISPLAY=:98
RESTARTS=0

# Page-level watchdog (capture-watchdog.py), run by THIS loop, not a daemon.
# Detects a crashed/frozen renderer (SIGTRAP "Aw, Snap") even while the
# Chromium and FFmpeg processes stay alive, restarts with cooldown/backoff and
# an hourly cap, and holds during site/network outages.
# Rollback switch: CNT_WATCHDOG=off restores the previous process-only check.
CNT_WATCHDOG="${CNT_WATCHDOG:-on}"
export CNT_WATCHDOG_DIR="${CNT_WATCHDOG_DIR:-/cnt-state/watchdog}"
export BROADCAST_ORIGIN CNT_CHROME_PROFILE=/tmp/cnt-chrome
mkdir -p "$CNT_WATCHDOG_DIR" || exit 1
chmod 700 "$CNT_WATCHDOG_DIR" || exit 1
# Host-local lifetime fence: all CNT instances MUST mount the same state root.
# Children must close fd 8; no encoder starts until this lifetime lock is held.
exec 8>"$CNT_WATCHDOG_DIR/encoder.lock"
flock -n 8 || { echo '[cnt] encoder fence held; refusing second sender' >&2; exit 1; }
# Only a stale FIFO is removed, after acquiring the lifetime fence.
[ -p "$CNT_WATCHDOG_DIR/chromium.pipe" ] && rm -- "$CNT_WATCHDOG_DIR/chromium.pipe"
export CNT_CHROME_LOG="$CNT_WATCHDOG_DIR/chromium.log"
LAST_ACTION=""

log() { echo "[$(date -u +%FT%TZ)] [cnt] $*"; }

start_display() {
  Xvfb :98 -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
  XVFB_PID=$!
  pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1 &
  PULSE_PID=$!
  sleep 2
  pactl load-module module-null-sink sink_name=cnt sink_properties=device.description=cnt >/dev/null
  pactl set-default-sink cnt
}

# Chromium stderr always goes through the sanitized bounded collector.
# Optional observer uses the same contract; no signed URLs survive logging.
CNT_AIR_LOG="${CNT_AIR_LOG:-}"
CHROME_LOG_FLAGS="--enable-logging=stderr --v=0"
if [ -n "$CNT_AIR_LOG" ]; then export CNT_CHROME_LOG="$CNT_AIR_LOG"; fi
# Optional extra Chromium flags for a trial after crash evidence (default none).
CNT_CHROME_EXTRA_FLAGS="${CNT_CHROME_EXTRA_FLAGS:-}"
# Opt-in (default OFF): loopback MPEG-TS tap for cnt-rolling-recorder.sh.
# onfail=ignore: a missing/slow tap can never stop the YouTube output.
CNT_ARCHIVE_TAP="${CNT_ARCHIVE_TAP:-}"   # e.g. udp://127.0.0.1:24010?pkt_size=1316

start_chromium() {
  # Keep the existing profile/minidump evidence. No periodic profile deletion.
  printf 'EPIC_CHROME_RESTART %s\n' "$(date -u +%FT%T.%3NZ)" | python3 ./cnt-diagnostics.py
  local fifo="$CNT_WATCHDOG_DIR/chromium.pipe"
  [ -e "$fifo" ] && { log "stale diagnostic pipe; refusing unsafe start"; return 1; }
  mkfifo -m 600 "$fifo" || return 1
  python3 ./cnt-diagnostics.py <"$fifo" 8>&- 9>&- &
  COLLECTOR_PID=$!
  # shellcheck disable=SC2086
  start_browser_group chromium --kiosk --no-first-run --no-default-browser-check --disable-infobars \
    --autoplay-policy=no-user-gesture-required --window-position=0,0 --window-size=1280,720 \
    --force-device-scale-factor=1 --disable-features=Translate,MediaRouter --noerrdialogs \
    --disable-session-crashed-bubble --user-data-dir=/tmp/cnt-chrome \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 \
    --disable-dev-shm-usage --no-sandbox $CHROME_LOG_FLAGS $CNT_CHROME_EXTRA_FLAGS "$URL" >"$fifo" 2>&1
  CHROME_STARTED=$(date +%s)
  [ "$CNT_WATCHDOG" != off ] && python3 ./capture-watchdog.py cnt started >/dev/null 2>&1
  log "chromium session $CHROME_PID started"
}

# Stop the whole CNT browser tree and wait, so the next start never races the
# old process for port 9223 or the profile dir. Scoped to the CNT profile only.
stop_chromium() {
  stop_browser_group || return 1
  # Collector sees EOF after every browser descendant closes stderr.
  if [[ "${COLLECTOR_PID:-}" =~ ^[1-9][0-9]+$ ]]; then
    for _ in $(seq 1 20); do kill -0 "$COLLECTOR_PID" 2>/dev/null || break; sleep 0.1; done
    kill "$COLLECTOR_PID" 2>/dev/null || true
    wait "$COLLECTOR_PID" 2>/dev/null || true
  fi
  # Remove ONLY our FIFO, never diagnostics/profile/media.
  [ -p "$CNT_WATCHDOG_DIR/chromium.pipe" ] && rm -- "$CNT_WATCHDOG_DIR/chromium.pipe"
  return 0
}

# One browser restart at a time (fd 9 lock).
exec 9>"$CNT_WATCHDOG_DIR/restart.lock"
restart_chromium() {
  if ! flock -n 9; then log "chromium restart skipped: another restart holds the lock"; return; fi
  if stop_chromium; then start_chromium || log "ALERT browser launch failed";
  else log "ALERT browser tree did not stop; replacement refused"; fi
  flock -u 9
}

cnt_output_args() {
  if [[ "$CNT_ARCHIVE_TAP" == udp://127.0.0.1:* ]]; then
    OUT_ARGS=(-f tee "[f=flv:onfail=abort]$CNT_DEST|[f=mpegts:onfail=ignore]$CNT_ARCHIVE_TAP")
  else OUT_ARGS=(-f flv "$CNT_DEST"); fi
}

start_ffmpeg() {
  rm -f "$PROGRESS"
  cnt_output_args
  # YouTube-compatible: 1280x720 30fps H.264 CBR, 2s GOP, AAC 48 kHz stereo.
  ffmpeg -hide_banner -loglevel warning -nostdin \
    -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1280x720 -framerate 30 -i :98.0 \
    -thread_queue_size 1024 -f pulse -i cnt.monitor \
    -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p \
    -b:v "$VIDEO_BITRATE" -minrate "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -bufsize "$((${VIDEO_BITRATE%k} * 2))k" \
    -x264-params nal-hrd=cbr -g 60 -keyint_min 60 -sc_threshold 0 \
    -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2 \
    -map 0:v -map 1:a -flags +global_header \
    -progress "$PROGRESS" "${OUT_ARGS[@]}" >/dev/null 2>&1 8>&- 9>&- &
  FFMPEG_PID=$!
  log "ffmpeg pid $FFMPEG_PID -> cnt youtube ingest"
}

# Watchdog tick: logs only when the decision changes (no log flood).
watch_browser() {
  local flag="" action
  kill -0 "$CHROME_PID" 2>/dev/null || flag="--process-exited"
  action=$(python3 ./capture-watchdog.py cnt tick $flag 2>>"$CNT_WATCHDOG_DIR/watchdog.err" | tail -1)
  [ -n "$action" ] || action="hold watchdog_no_output"
  case "$action" in
    *watchdog_error*|*watchdog_no_output*|*ALERT_state_invalid*)
      [ "$action" != "$LAST_ACTION" ] && log "ALERT recovery policy unavailable; automatic restart refused" ;;
  esac
  case "$action" in
    restart*) RESTARTS=$((RESTARTS + 1)); log "watchdog $action -> restart chromium (#$RESTARTS)"; restart_chromium ;;
    *) [ "$action" != "$LAST_ACTION" ] && log "watchdog $action" ;;
  esac
  LAST_ACTION="$action"
}

stop_owned() {
  local pid="${1:-}"
  [[ "$pid" =~ ^[1-9][0-9]+$ ]] && [ "$pid" -gt 1 ] || return 0
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
shutdown() {
  trap '' TERM INT
  stop_owned "${FFMPEG_PID:-}"
  stop_chromium || true
  stop_owned "${XVFB_PID:-}"
  stop_owned "${PULSE_PID:-}"
  exit 0
}
trap shutdown TERM INT

start_display
start_chromium || exit 1
sleep 8
start_ffmpeg

while sleep 5; do
  now=$(date +%s)
  if [ "$CNT_WATCHDOG" = off ]; then
    # Previous behavior (rollback): browser process / DevTools only.
    if ! kill -0 "$CHROME_PID" 2>/dev/null || ! curl -sf -m 3 http://127.0.0.1:9223/json/version >/dev/null; then
      # Rollback changes probing only; restart still uses the bounded policy.
      watch_browser
    fi
  else
    watch_browser
  fi
  if ! kill -0 "$FFMPEG_PID" 2>/dev/null; then
    RESTARTS=$((RESTARTS + 1)); log "restart ffmpeg exited (#$RESTARTS)"; stop_owned "$FFMPEG_PID"; sleep 2; start_ffmpeg; continue
  fi
  if [ -f "$PROGRESS" ] && [ $((now - $(stat -c %Y "$PROGRESS"))) -gt "$STALL_SECONDS" ]; then
    RESTARTS=$((RESTARTS + 1)); log "restart ffmpeg stalled (#$RESTARTS)"; stop_owned "$FFMPEG_PID"; sleep 2; start_ffmpeg
  fi
done
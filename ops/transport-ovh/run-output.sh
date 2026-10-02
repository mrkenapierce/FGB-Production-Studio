#!/usr/bin/env bash
set -uo pipefail
: "${OUTPUT:?OUTPUT required}"
: "${BROADCAST_ORIGIN:?BROADCAST_ORIGIN required}"
MODE="${OUTPUT}"
case "$OUTPUT" in
  youtube)
    # Keep the production YouTube path self-contained and independent of bridge targets.
    TARGET="youtube" ;;
  rumble_bridge)
    TARGET="${BRIDGE_RENDER_TARGET:-rumble}"
    : "${RUMBLE_STUDIO_INGEST_URL:?RUMBLE_STUDIO_INGEST_URL required for rumble_bridge}"
    : "${RUMBLE_STUDIO_STREAM_KEY:?RUMBLE_STUDIO_STREAM_KEY required for rumble_bridge}"
    DESTINATIONS="${RUMBLE_STUDIO_INGEST_URL%/}/${RUMBLE_STUDIO_STREAM_KEY}"
    VIDEO_BITRATE="${VIDEO_BITRATE:-3000k}"; AUDIO_BITRATE="${AUDIO_BITRATE:-128k}" ;;
  *) echo "bad OUTPUT"; exit 2 ;;
esac
export MODE DESTINATIONS
VIDEO_BITRATE="${VIDEO_BITRATE:-3000k}"
AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"
STALL_SECONDS="${STALL_SECONDS:-20}"
RELOAD_EVERY_SECONDS="${RELOAD_EVERY_SECONDS:-21600}"
URL="${BROADCAST_ORIGIN%/}/fgb-broadcast?target=${TARGET}"
PROGRESS=/tmp/fgb-ffmpeg.progress
STATE=/tmp/fgb-transport.state
ARCHIVE_ENABLED="${FGB_ARCHIVE_ENABLED:-1}"
ARCHIVE_UDP_OUTPUT="${FGB_ARCHIVE_LOCAL_UDP_OUTPUT_URL:-udp://127.0.0.1:1944?pkt_size=1316}"
ARCHIVE_PID=""
ARCHIVE_LAST_START=0
export DISPLAY=:99
[ -n "${DESTINATIONS:-}" ] || { echo "DESTINATIONS required"; exit 2; }
RESTARTS=0
CHROMIUM_FAILURES=0
STARTED=$(date +%s)
echo starting > "$STATE"; echo 0 > /tmp/fgb-restarts
log() { echo "[$(date -u +%FT%TZ)] [$OUTPUT] $*"; }
start_display() {
  Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 & XVFB_PID=$!
  pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1 &
  sleep 2
  pactl load-module module-null-sink sink_name=fgb sink_properties=device.description=fgb >/dev/null
  pactl set-default-sink fgb
}
start_chromium() {
  rm -rf /tmp/fgb-chrome
  chromium --kiosk --start-fullscreen --no-first-run --no-default-browser-check --disable-infobars --autoplay-policy=no-user-gesture-required --window-position=0,0 --window-size=1280,720 --force-device-scale-factor=1 --disable-gpu --use-gl=swiftshader --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --disable-features=Translate,MediaRouter --noerrdialogs --disable-session-crashed-bubble --user-data-dir=/tmp/fgb-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --disable-dev-shm-usage --no-sandbox "$URL" >/dev/null 2>&1 &
  CHROME_PID=$!; CHROME_STARTED=$(date +%s); CHROMIUM_FAILURES=0; log "chromium pid $CHROME_PID -> $URL"
}
wait_for_chromium() {
  for _ in $(seq 1 30); do
    if kill -0 "$CHROME_PID" 2>/dev/null && curl -sf -m 3 http://127.0.0.1:9222/json/version >/dev/null; then
      sleep 5
      log "chromium ready for capture"
      return 0
    fi
    sleep 1
  done
  log "chromium did not become capture-ready in time"
  return 1
}
start_archive_recorder() {
  if [ "$OUTPUT" != youtube ] || [ "$ARCHIVE_ENABLED" != 1 ]; then return 0; fi
  ARCHIVE_LAST_START=$(date +%s)
  ./archive-recorder.sh >>/tmp/fgb-archive-recorder.log 2>&1 &
  ARCHIVE_PID=$!
  log "archive recorder pid $ARCHIVE_PID (isolated loopback tap)"
}
start_ffmpeg() {
  rm -f "$PROGRESS"
  if [ "$OUTPUT" = youtube ] && [ "$ARCHIVE_ENABLED" = 1 ]; then
    # The YouTube leg remains fatal so the existing watchdog reconnects it.
    # The archive leg is explicitly onfail=ignore and writes only to loopback UDP,
    # so recorder/storage/upload failures cannot stop the live destination.
    TEE_DESTINATIONS="[f=flv:onfail=abort]${DESTINATIONS}|[f=mpegts:onfail=ignore]${ARCHIVE_UDP_OUTPUT}"
    ffmpeg -hide_banner -loglevel warning -nostdin -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1280x720 -framerate 30 -i :99.0 -thread_queue_size 1024 -f pulse -i fgb.monitor -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -b:v "$VIDEO_BITRATE" -minrate "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -bufsize "$((${VIDEO_BITRATE%k} * 2))k" -x264-params nal-hrd=cbr -g 60 -keyint_min 60 -sc_threshold 0 -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2 -map 0:v -map 1:a -flags +global_header -progress "$PROGRESS" -f tee "$TEE_DESTINATIONS" &
  else
    ffmpeg -hide_banner -loglevel warning -nostdin -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1280x720 -framerate 30 -i :99.0 -thread_queue_size 1024 -f pulse -i fgb.monitor -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -b:v "$VIDEO_BITRATE" -minrate "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -bufsize "$((${VIDEO_BITRATE%k} * 2))k" -x264-params nal-hrd=cbr -g 60 -keyint_min 60 -sc_threshold 0 -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2 -map 0:v -map 1:a -flags +global_header -progress "$PROGRESS" -f flv "$DESTINATIONS" &
  fi
  FFMPEG_PID=$!; log "ffmpeg pid $FFMPEG_PID"
}
restart() { RESTARTS=$((RESTARTS + 1)); echo "$RESTARTS" >/tmp/fgb-restarts; echo degraded > "$STATE"; log "restart $1 (#$RESTARTS)"; }
shutdown() { echo stopped > "$STATE"; [ -n "${HB_PID:-}" ] && ./heartbeat.sh once || true; kill "${FFMPEG_PID:-0}" "${CHROME_PID:-0}" "${ARCHIVE_PID:-0}" "${HB_PID:-0}" "${XVFB_PID:-0}" 2>/dev/null; exit 0; }
trap shutdown TERM INT
start_display
start_chromium
wait_for_chromium || { restart "chromium startup"; kill "$CHROME_PID" 2>/dev/null; start_chromium; wait_for_chromium || exit 3; }
start_archive_recorder
start_ffmpeg
if [ -n "${HEARTBEAT_URL:-}" ] && [ -n "${FGB_TRANSPORT_HEARTBEAT_SECRET:-}" ]; then STARTED="$STARTED" ./heartbeat.sh loop & HB_PID=$!; fi
while sleep 5; do
  now=$(date +%s)
  if ! kill -0 "$CHROME_PID" 2>/dev/null || ! curl -sf -m 3 http://127.0.0.1:9222/json/version >/dev/null; then
    CHROMIUM_FAILURES=$((CHROMIUM_FAILURES + 1))
    log "chromium health check failed ($CHROMIUM_FAILURES/3)"
    if [ "$CHROMIUM_FAILURES" -ge 3 ]; then
      restart chromium
      kill "$CHROME_PID" 2>/dev/null
      start_chromium
      wait_for_chromium || true
    fi
  else
    CHROMIUM_FAILURES=0
    if [ $((now - CHROME_STARTED)) -ge "$RELOAD_EVERY_SECONDS" ]; then
      kill "$CHROME_PID" 2>/dev/null
      start_chromium
      wait_for_chromium || true
    fi
  fi
  if ! kill -0 "$FFMPEG_PID" 2>/dev/null; then restart "ffmpeg exited"; sleep 2; start_ffmpeg; continue; fi
  if [ -f "$PROGRESS" ] && [ $((now - $(stat -c %Y "$PROGRESS"))) -gt "$STALL_SECONDS" ]; then restart "ffmpeg stalled"; kill -9 "$FFMPEG_PID" 2>/dev/null; sleep 2; start_ffmpeg; continue; fi
  if grep -q "progress=continue" "$PROGRESS" 2>/dev/null; then echo live > "$STATE"; fi
  if [ "$OUTPUT" = youtube ] && [ "$ARCHIVE_ENABLED" = 1 ]; then
    if [ -z "$ARCHIVE_PID" ] || ! kill -0 "$ARCHIVE_PID" 2>/dev/null; then
      if [ $((now - ARCHIVE_LAST_START)) -ge 60 ]; then
        log "archive recorder unavailable; restarting recorder without touching live ffmpeg"
        start_archive_recorder
      fi
    fi
  fi
done

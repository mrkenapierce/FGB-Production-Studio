#!/usr/bin/env bash
# CNT (CruiseNewsTrivia) capture ONLY. Independent of every FGB output:
# renders /channels/cruisenewstrivia/broadcast, sends ONE RTMP(S) stream to the
# CNT YouTube ingest, no heartbeat, no archive tap, no shared secrets.
set -uo pipefail

: "${BROADCAST_ORIGIN:?BROADCAST_ORIGIN required}"
: "${CNT_YOUTUBE_INGEST_URL:?CNT_YOUTUBE_INGEST_URL required}"
: "${CNT_YOUTUBE_STREAM_KEY:?CNT_YOUTUBE_STREAM_KEY required}"
CNT_DEST="${CNT_YOUTUBE_INGEST_URL%/}/${CNT_YOUTUBE_STREAM_KEY}"   # never logged
URL="${BROADCAST_ORIGIN%/}/channels/cruisenewstrivia/broadcast"
VIDEO_BITRATE="${CNT_VIDEO_BITRATE:-3000k}"
AUDIO_BITRATE="${CNT_AUDIO_BITRATE:-128k}"
STALL_SECONDS="${CNT_STALL_SECONDS:-20}"
RELOAD_EVERY_SECONDS="${CNT_RELOAD_EVERY_SECONDS:-21600}"
PROGRESS=/tmp/cnt-ffmpeg.progress
export DISPLAY=:98
RESTARTS=0

log() { echo "[$(date -u +%FT%TZ)] [cnt] $*"; }

start_display() {
  Xvfb :98 -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
  XVFB_PID=$!
  pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1 &
  sleep 2
  pactl load-module module-null-sink sink_name=cnt sink_properties=device.description=cnt >/dev/null
  pactl set-default-sink cnt
}

# Opt-in (default OFF): Chromium console log for the trusted air observer
# (cnt-air-observer.py). The restart marker lets the observer interrupt any
# open play when the browser restarts. No secret is ever given to the browser.
CNT_AIR_LOG="${CNT_AIR_LOG:-}"
if [ -n "$CNT_AIR_LOG" ]; then CHROME_LOG_FLAGS="--enable-logging=stderr --v=0"; CHROME_LOG_TARGET="$CNT_AIR_LOG"
else CHROME_LOG_FLAGS=""; CHROME_LOG_TARGET=/dev/null; fi
# Opt-in (default OFF): loopback MPEG-TS archive tap for cnt-rolling-recorder.sh.
# onfail=ignore: a missing/slow tap can never stop the YouTube output.
CNT_ARCHIVE_TAP="${CNT_ARCHIVE_TAP:-}"   # e.g. udp://127.0.0.1:24010?pkt_size=1316

start_chromium() {
  [ -n "$CNT_AIR_LOG" ] && echo "EPIC_CHROME_RESTART $(date -u +%FT%T.%3NZ)" >> "$CNT_AIR_LOG"
  rm -rf /tmp/cnt-chrome
  chromium --kiosk --no-first-run --no-default-browser-check --disable-infobars \
    --autoplay-policy=no-user-gesture-required --window-position=0,0 --window-size=1280,720 \
    --force-device-scale-factor=1 --disable-features=Translate,MediaRouter --noerrdialogs \
    --disable-session-crashed-bubble --user-data-dir=/tmp/cnt-chrome \
    --remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 \
    --disable-dev-shm-usage --no-sandbox $CHROME_LOG_FLAGS "$URL" >>"$CHROME_LOG_TARGET" 2>&1 &
  CHROME_PID=$!
  CHROME_STARTED=$(date +%s)
  log "chromium pid $CHROME_PID -> $URL"
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
    -progress "$PROGRESS" "${OUT_ARGS[@]}" >/dev/null 2>&1 &
  FFMPEG_PID=$!
  log "ffmpeg pid $FFMPEG_PID -> cnt youtube ingest"
}

shutdown() { kill "${FFMPEG_PID:-0}" "${CHROME_PID:-0}" "${XVFB_PID:-0}" 2>/dev/null; exit 0; }
trap shutdown TERM INT

start_display
start_chromium
sleep 8
start_ffmpeg

while sleep 5; do
  now=$(date +%s)
  if ! kill -0 "$CHROME_PID" 2>/dev/null || ! curl -sf -m 3 http://127.0.0.1:9223/json/version >/dev/null; then
    RESTARTS=$((RESTARTS + 1)); log "restart chromium (#$RESTARTS)"; kill "$CHROME_PID" 2>/dev/null; start_chromium
  elif [ $((now - CHROME_STARTED)) -ge "$RELOAD_EVERY_SECONDS" ]; then
    log "scheduled chromium refresh"; kill "$CHROME_PID" 2>/dev/null; start_chromium
  fi
  if ! kill -0 "$FFMPEG_PID" 2>/dev/null; then
    RESTARTS=$((RESTARTS + 1)); log "restart ffmpeg exited (#$RESTARTS)"; sleep 2; start_ffmpeg; continue
  fi
  if [ -f "$PROGRESS" ] && [ $((now - $(stat -c %Y "$PROGRESS"))) -gt "$STALL_SECONDS" ]; then
    RESTARTS=$((RESTARTS + 1)); log "restart ffmpeg stalled (#$RESTARTS)"; kill -9 "$FFMPEG_PID" 2>/dev/null; sleep 2; start_ffmpeg
  fi
done
#!/usr/bin/env bash
set -uo pipefail
: "${OUTPUT:?OUTPUT required (youtube|general)}"
: "${BROADCAST_ORIGIN:?BROADCAST_ORIGIN required}"
DRY_RUN="${DRY_RUN:-0}"
if [ "$DRY_RUN" != "1" ]; then : "${DESTINATIONS:?DESTINATIONS required unless DRY_RUN=1}"; fi
case "$OUTPUT" in youtube) TARGET=youtube ;; general) TARGET=rumble ;; *) exit 2 ;; esac
VIDEO_BITRATE="${VIDEO_BITRATE:-4500k}"
AUDIO_BITRATE="${AUDIO_BITRATE:-160k}"
URL="${BROADCAST_ORIGIN%/}/fgb-broadcast?target=${TARGET}"
export DISPLAY=:99
PROGRESS=/tmp/fgb-ffmpeg.progress
STATE=/tmp/fgb-transport.state
echo starting > "$STATE"
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1 &
sleep 2
pactl load-module module-null-sink sink_name=fgb sink_properties=device.description=fgb >/dev/null
pactl set-default-sink fgb
chromium --kiosk --no-first-run --no-default-browser-check --disable-infobars --autoplay-policy=no-user-gesture-required --window-position=0,0 --window-size=1280,720 --force-device-scale-factor=1 --disable-features=Translate,MediaRouter --noerrdialogs --disable-session-crashed-bubble --user-data-dir=/tmp/fgb-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --disable-dev-shm-usage --no-sandbox "$URL" >/dev/null 2>&1 &
sleep 8
tee_targets() { local out="" d; for d in $DESTINATIONS; do out="${out:+$out|}[f=flv:onfail=ignore]$d"; done; echo "$out"; }
if [ -n "${HEARTBEAT_URL:-}" ] && [ -n "${FGB_TRANSPORT_HEARTBEAT_SECRET:-}" ]; then ./heartbeat.sh & fi
COMMON=(-hide_banner -loglevel warning -nostdin -thread_queue_size 1024 -f x11grab -draw_mouse 0 -video_size 1280x720 -framerate 30 -i :99.0 -thread_queue_size 1024 -f pulse -i fgb.monitor -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -b:v "$VIDEO_BITRATE" -minrate "$VIDEO_BITRATE" -maxrate "$VIDEO_BITRATE" -bufsize 9000k -x264-params nal-hrd=cbr -g 60 -keyint_min 60 -sc_threshold 0 -c:a aac -b:a "$AUDIO_BITRATE" -ar 48000 -ac 2 -map 0:v -map 1:a -progress "$PROGRESS")
if [ "$DRY_RUN" = "1" ]; then
  echo live > "$STATE"
  ffmpeg "${COMMON[@]}" -f null -
else
  ffmpeg "${COMMON[@]}" -flags +global_header -f tee "$(tee_targets)"
fi
echo stopped > "$STATE"
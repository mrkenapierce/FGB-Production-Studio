#!/usr/bin/env bash
set -Eeuo pipefail

# Native-size YouTube-only compositor. The 1280x720/30 master is never scaled;
# only the exact Lovable trivia question rectangle is replaced on YouTube.
# The static RGBA cover runs at 15fps and FFmpeg repeats its most recent frame
# over the 30fps base. This cuts unnecessary overlay IPC roughly in half without
# reducing the program frame rate. Rumble remains on the untouched master.

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
YOUTUBE_QUESTION_MASK_PORT=8791
YOUTUBE_OUTPUT_WIDTH=1280
YOUTUBE_OUTPUT_HEIGHT=720
YOUTUBE_OUTPUT_FPS=30
YOUTUBE_OVERLAY_FPS=15
YOUTUBE_VIDEO_BITRATE=3500k
YOUTUBE_VIDEO_MAXRATE=4000k
YOUTUBE_VIDEO_BUFSIZE=7000k
YOUTUBE_AUDIO_SAMPLE_RATE=48000
YOUTUBE_AUDIO_BITRATE=128k
YOUTUBE_AUDIO_CHANNELS=2
YOUTUBE_MONITOR_DIR=${YOUTUBE_MONITOR_DIR:-/run/fgbears-youtube-lovable-compositor}
YOUTUBE_UDP_FIFO_SIZE=1000000
YOUTUBE_MASTER_THREAD_QUEUE=512
YOUTUBE_OVERLAY_THREAD_QUEUE=16

[[ -d "$YOUTUBE_MONITOR_DIR" && -w "$YOUTUBE_MONITOR_DIR" ]] || {
  echo "Monitor runtime directory unavailable: $YOUTUBE_MONITOR_DIR" >&2
  exit 78
}

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=${YOUTUBE_UDP_FIFO_SIZE}&overrun_nonfatal=1&reuse=1"
HEALTH_URL="http://127.0.0.1:${YOUTUBE_QUESTION_MASK_PORT}/healthz"
OVERLAY_URL="http://127.0.0.1:${YOUTUBE_QUESTION_MASK_PORT}/overlay.rgba"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
MONITOR_PATTERN="${YOUTUBE_MONITOR_DIR%/}/monitor-%d.ts"
FIFO_OPTIONS='attempt_recovery=1:recover_any_error=1:recovery_wait_time=1:drop_pkts_on_overflow=1:restart_with_keyframe=1'
rm -f "${YOUTUBE_MONITOR_DIR%/}"/monitor-*.ts

health=$(curl -fsS --max-time 3 "$HEALTH_URL")
read -r MASK_X MASK_Y MASK_WIDTH MASK_HEIGHT <<EOF
$(printf '%s' "$health" | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True
assert p.get("sourceCanvas")==[1280,720]
assert p.get("canvas")==[1280,720]
assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("maskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("frameSize")==[798,470]
assert p.get("creativeKey")=="yt_rumble_trivia_redirect"
r=p["maskRegion"]
print(r["x"],r["y"],r["width"],r["height"])
')
EOF

echo "Starting 1280x720/30 YouTube compositor; exact trivia box=${MASK_X},${MASK_Y} ${MASK_WIDTH}x${MASK_HEIGHT}; overlay=${YOUTUBE_OVERLAY_FPS}fps; video=3500k; AAC 48k stereo." >&2

exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size "$YOUTUBE_MASTER_THREAD_QUEUE" -i "$LOCAL_INPUT" \
  -thread_queue_size "$YOUTUBE_OVERLAY_THREAD_QUEUE" \
  -f rawvideo -pixel_format rgba -video_size "${MASK_WIDTH}x${MASK_HEIGHT}" -framerate "$YOUTUBE_OVERLAY_FPS" -i "$OVERLAY_URL" \
  -filter_complex "[0:v:0]setsar=1[base];[base][1:v:0]overlay=${MASK_X}:${MASK_Y}:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v]" \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r "$YOUTUBE_OUTPUT_FPS" -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v "$YOUTUBE_VIDEO_BITRATE" -maxrate "$YOUTUBE_VIDEO_MAXRATE" -bufsize "$YOUTUBE_VIDEO_BUFSIZE" \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a "$YOUTUBE_AUDIO_BITRATE" -ar "$YOUTUBE_AUDIO_SAMPLE_RATE" -ac "$YOUTUBE_AUDIO_CHANNELS" \
  -af "aresample=${YOUTUBE_AUDIO_SAMPLE_RATE}:async=1:first_pts=0" \
  -f tee -use_fifo 1 -fifo_options "$FIFO_OPTIONS" \
  "[f=flv:onfail=abort]${UPSTREAM_TARGET}|[f=segment:segment_time=2:segment_wrap=3:segment_format=mpegts:reset_timestamps=1:onfail=ignore]${MONITOR_PATTERN}"

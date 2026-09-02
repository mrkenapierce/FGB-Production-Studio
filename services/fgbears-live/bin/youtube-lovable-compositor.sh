#!/usr/bin/env bash
set -Eeuo pipefail

# Resource-protected YouTube-only media executor for the Lovable routing plane.
# Rumble remains on the untouched 1280x720 shared master. This branch renders
# YouTube at 640x360/30fps because that is the highest same-host tier with a
# measured production CPU safety margin. The upper news and lower crawl remain
# live because the moving master is continuously decoded/scaled; only Lovable's
# question panel is overlaid when the routing consumer emits opaque RGBA.

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${YOUTUBE_QUESTION_MASK_PORT:=8791}"
: "${YOUTUBE_OUTPUT_WIDTH:=640}"
: "${YOUTUBE_OUTPUT_HEIGHT:=360}"
: "${YOUTUBE_OUTPUT_FPS:=30}"
: "${YOUTUBE_VIDEO_BITRATE:=2200k}"
: "${YOUTUBE_VIDEO_MAXRATE:=2500k}"
: "${YOUTUBE_VIDEO_BUFSIZE:=4400k}"

[[ "$YOUTUBE_OUTPUT_WIDTH" == 640 && "$YOUTUBE_OUTPUT_HEIGHT" == 360 && "$YOUTUBE_OUTPUT_FPS" == 30 ]] || {
  echo "Same-host Lovable compositor is safety-qualified only for 640x360 at 30 fps." >&2
  exit 78
}

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
HEALTH_URL="http://127.0.0.1:${YOUTUBE_QUESTION_MASK_PORT}/healthz"
OVERLAY_URL="http://127.0.0.1:${YOUTUBE_QUESTION_MASK_PORT}/overlay.rgba"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

health=$(curl -fsS --max-time 3 "$HEALTH_URL")
read -r MASK_X MASK_Y MASK_WIDTH MASK_HEIGHT CREATIVE AUTHORITY <<EOF
$(printf '%s' "$health" | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("ok") is True
assert p.get("sourceCanvas")==[1280,720]
assert p.get("canvas")==[640,360]
assert p.get("sourceMaskRegion")=={"x":462,"y":104,"width":798,"height":470}
assert p.get("creativeKey")=="yt_rumble_trivia_redirect"
assert p.get("presentationMode")=="full_creative_scaled"
assert p.get("routingAuthority")=="lovable_public_stream_routing"
r=p["maskRegion"]
assert r=={"x":231,"y":52,"width":399,"height":235},r
print(r["x"],r["y"],r["width"],r["height"],p["creativeKey"],p["routingAuthority"])
')
EOF

[[ "$CREATIVE" == yt_rumble_trivia_redirect && "$AUTHORITY" == lovable_public_stream_routing ]]

echo "Starting Lovable-controlled YouTube compositor: 640x360/30, panel=${MASK_X},${MASK_Y} ${MASK_WIDTH}x${MASK_HEIGHT}." >&2

# A single video encode feeds both YouTube and a loopback MPEG-TS monitor. The
# monitor exists only for read-only verification and costs no second encode.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -fflags +genpts+discardcorrupt -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -f rawvideo -pixel_format rgba -video_size "${MASK_WIDTH}x${MASK_HEIGHT}" -framerate "$YOUTUBE_OUTPUT_FPS" \
  -i "$OVERLAY_URL" \
  -filter_complex "[0:v:0]scale=${YOUTUBE_OUTPUT_WIDTH}:${YOUTUBE_OUTPUT_HEIGHT}:flags=fast_bilinear[base];[base][1:v:0]overlay=${MASK_X}:${MASK_Y}:format=auto:shortest=1[v]" \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high \
  -pix_fmt yuv420p -r "$YOUTUBE_OUTPUT_FPS" -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v "$YOUTUBE_VIDEO_BITRATE" -maxrate "$YOUTUBE_VIDEO_MAXRATE" -bufsize "$YOUTUBE_VIDEO_BUFSIZE" \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a 128k -ar 44100 -ac 2 \
  -af 'aresample=44100:async=1:first_pts=0' \
  -f tee -use_fifo 1 -fifo_options 'attempt_recovery=1:recover_any_error=1' \
  "[f=flv:onfail=abort]${UPSTREAM_TARGET}|[f=mpegts:onfail=ignore]udp://127.0.0.1:1941?pkt_size=1316"

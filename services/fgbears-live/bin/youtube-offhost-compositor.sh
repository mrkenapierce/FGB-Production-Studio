#!/usr/bin/env bash
set -Eeuo pipefail

# Dedicated/off-host YouTube compositor. Lovable is the routing/control plane;
# youtube-question-mask.py consumes that contract and publishes the exact active
# mask geometry through /healthz. This compositor refuses to start until that
# contract is healthy, then overlays only the Lovable-defined trivia panel onto
# continuously moving live video. RSS/news and crawl remain live at all times.

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
SRT_LISTEN_PORT="${FGB_COMPOSITOR_SRT_PORT:-9000}"
MASK_PORT="${YOUTUBE_QUESTION_MASK_PORT:-8791}"
YOUTUBE_BASE="${YOUTUBE_UPSTREAM_RTMP_BASE:-rtmps://a.rtmps.youtube.com/live2}"
VIDEO_BITRATE="${FGB_COMPOSITOR_VIDEO_BITRATE:-5000k}"
VIDEO_MAXRATE="${FGB_COMPOSITOR_VIDEO_MAXRATE:-5500k}"
VIDEO_BUFSIZE="${FGB_COMPOSITOR_VIDEO_BUFSIZE:-10000k}"
X264_PRESET="${FGB_COMPOSITOR_X264_PRESET:-veryfast}"
THREADS="${FGB_COMPOSITOR_THREADS:-0}"
MASK_HEALTH="http://127.0.0.1:${MASK_PORT}/healthz"

contract_json=""
for _ in $(seq 1 60); do
  if contract_json=$(curl --silent --fail --max-time 2 "$MASK_HEALTH" 2>/dev/null); then
    break
  fi
  sleep 1
done
[[ -n "$contract_json" ]] || { echo "Lovable-driven mask renderer is not healthy" >&2; exit 69; }

# Parse and validate the execution contract without jq. The mask worker itself
# obtained these values from Lovable's /api/public/fgbears/stream-routing.
read -r MASK_X MASK_Y MASK_WIDTH MASK_HEIGHT CREATIVE MODE AUTHORITY < <(
  python3 -c '
import json, sys
p=json.load(sys.stdin)
r=p.get("maskRegion") or {}
vals=(r.get("x"),r.get("y"),r.get("width"),r.get("height"),p.get("creativeKey"),p.get("presentationMode"),p.get("routingAuthority"))
if p.get("ok") is not True: raise SystemExit("mask renderer unhealthy")
if vals[4] != "yt_rumble_trivia_redirect": raise SystemExit("unexpected creative")
if vals[5] != "full_creative_scaled": raise SystemExit("unexpected presentation mode")
if vals[6] != "lovable_public_stream_routing": raise SystemExit("unexpected routing authority")
x,y,w,h=map(int,vals[:4])
if w <= 0 or h <= 0 or x < 0 or y < 104 or x+w > 1280 or y+h > 574:
    raise SystemExit("mask geometry violates live news/crawl safety bands")
print(x,y,w,h,vals[4],vals[5],vals[6])
' <<<"$contract_json"
)

# Hard safety boundary: the raw RGBA input is exactly the Lovable-published
# trivia panel size, never a 1280x720 full-frame overlay. Only this region can
# become opaque; the continuously moving program, RSS/news and crawl remain the
# underlying live video.
exec ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts \
  -probesize 10000000 -analyzeduration 10000000 \
  -i "srt://0.0.0.0:${SRT_LISTEN_PORT}?mode=listener&latency=200000&rcvlatency=200000&peerlatency=200000" \
  -f rawvideo -pixel_format rgba -video_size "${MASK_WIDTH}x${MASK_HEIGHT}" -framerate 30 \
  -i "http://127.0.0.1:${MASK_PORT}/overlay.rgba" \
  -filter_complex "[0:v:0][1:v:0]overlay=${MASK_X}:${MASK_Y}:format=auto:shortest=1[v]" \
  -map '[v]' -map 0:a:0 \
  -c:v libx264 -preset "$X264_PRESET" -tune zerolatency \
  -profile:v high -pix_fmt yuv420p -r 30 -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v "$VIDEO_BITRATE" -maxrate "$VIDEO_MAXRATE" -bufsize "$VIDEO_BUFSIZE" \
  -threads "$THREADS" \
  -c:a copy \
  -f flv -flvflags no_duration_filesize \
  "${YOUTUBE_BASE%/}/${YOUTUBE_STREAM_KEY}"

#!/usr/bin/env bash
set -Eeuo pipefail

OUT_PORT=${FGB_YOUTUBE_DYNAMIC_CARD_PORT:-2942}
NEWS_URL=${FGB_YOUTUBE_NEWS_URL:-http://127.0.0.1:8789/overlay.mjpg}
CRAWL_URL=${FGB_YOUTUBE_CRAWL_URL:-http://127.0.0.1:8788/overlay.mjpg}
MASTER_URL=${FGB_YOUTUBE_MASTER_URL:-udp://127.0.0.1:1939?reuse=1&fifo_size=1000000&overrun_nonfatal=1}
WORK_DIR=${FGB_YOUTUBE_DYNAMIC_WORK_DIR:-/var/lib/fgbears-live/youtube-dynamic-card}
PYLIB=${FGB_YOUTUBE_EXACT_CARD_PYLIB:-/opt/fgbears-live/exact-card-pylib}
BUILD_CARD=${FGB_YOUTUBE_BUILD_CARD:-/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py}
COMPOSE_CARD=${FGB_YOUTUBE_COMPOSE_CARD:-/opt/fgbears-live/tools/compose-exact-youtube-card.py}
FPS=${FGB_YOUTUBE_DYNAMIC_FPS:-10}

install -d -m 0755 "$WORK_DIR"
frame="$WORK_DIR/frame.png"
source_card="$WORK_DIR/source-card.png"
base="$WORK_DIR/base.png"
compose_json="$WORK_DIR/compose.json"

# Capture one current full-size master frame. The exact-card compositor masks the
# complete Lovable-authoritative question/answer region before this frame can be
# used in the protected YouTube branch, so a restart during trivia cannot leak
# the question through the frozen middle panel.
timeout 15 ffmpeg -hide_banner -nostdin -loglevel error \
  -fflags +genpts -probesize 3000000 -analyzeduration 3000000 \
  -i "$MASTER_URL" -map 0:v:0 -frames:v 1 -y "$frame"
test -s "$frame"

PYTHONPATH="$PYLIB" /usr/bin/python3 "$BUILD_CARD" "$source_card" >/dev/null
test -s "$source_card"
PYTHONPATH="$PYLIB" /usr/bin/python3 "$COMPOSE_CARD" \
  "$frame" "$source_card" "$base" >"$compose_json"
test -s "$base"
# Production geometry must remain the current Lovable-authoritative 798x470
# middle panel. The exact 16:9 card is proportionally fitted at x=462,y=114.
grep -Fq '"x": 462' "$compose_json"
grep -Fq '"y": 114' "$compose_json"

# Only the RSS/news ribbon and trivia crawl are animated here. The protected
# middle frame is already safe and exact. Ten fps was measured at >1.4x real
# time on the current 0.5-OCPU production VM while the master/Rumble/YouTube
# services remained running, leaving a conservative real-time margin.
exec ffmpeg -hide_banner -nostdin -loglevel warning \
  -re -loop 1 -framerate "$FPS" -i "$base" \
  -thread_queue_size 64 -fflags +genpts -r "$FPS" -f mpjpeg -i "$NEWS_URL" \
  -thread_queue_size 64 -fflags +genpts -r "$FPS" -f mpjpeg -i "$CRAWL_URL" \
  -filter_complex "[1:v:0]fps=${FPS}[news];[2:v:0]fps=${FPS}[crawl];[0:v:0][news]overlay=0:0:shortest=1[n];[n][crawl]overlay=0:574:shortest=1,format=yuv420p[v]" \
  -map '[v]' -an \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v baseline -level:v 3.1 \
  -pix_fmt yuv420p -r "$FPS" -g $((FPS * 2)) -keyint_min $((FPS * 2)) -sc_threshold 0 -threads 1 \
  -b:v 5000k -maxrate 5500k -bufsize 10000k \
  -x264-params 'aud=1:repeat-headers=1' \
  -mpegts_flags +resend_headers -f mpegts \
  "udp://127.0.0.1:${OUT_PORT}?pkt_size=1316"

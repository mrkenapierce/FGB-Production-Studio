#!/usr/bin/env bash
set -Eeuo pipefail

# Source-host copy-only relay for the dedicated YouTube compositor.
# This performs no video decode or encode. It forwards the already-encoded
# master H.264/AAC program over SRT to the separate compositor worker.

: "${FGB_COMPOSITOR_HOST:?FGB_COMPOSITOR_HOST is required}"
INPUT_URL="${YOUTUBE_LOCAL_UDP_URL:-udp://127.0.0.1:1939?fifo_size=1000000&overrun_nonfatal=1&reuse=1}"
PORT="${FGB_COMPOSITOR_SRT_PORT:-9000}"

exec ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts -probesize 10000000 -analyzeduration 10000000 \
  -i "$INPUT_URL" \
  -map 0:v:0 -map 0:a:0 -c copy \
  -f mpegts \
  "srt://${FGB_COMPOSITOR_HOST}:${PORT}?mode=caller&latency=200000&peerlatency=200000"

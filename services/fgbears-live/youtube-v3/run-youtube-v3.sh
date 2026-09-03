#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_V3_BUFFERED_UDP_URL:=udp://127.0.0.1:1941?pkt_size=1316}"
: "${YOUTUBE_V3_BUFFER_SECONDS:=4}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${YOUTUBE_V3_STARTUP_DELAY_SECONDS:=0}"

[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "YouTube master mirror must be loopback UDP" >&2; exit 78; }
[[ "$YOUTUBE_V3_BUFFERED_UDP_URL" == udp://127.0.0.1:* ]] || { echo "YouTube buffered input must be loopback UDP" >&2; exit 78; }
[[ "$YOUTUBE_LOCAL_UDP_URL" != "$YOUTUBE_V3_BUFFERED_UDP_URL" ]] || { echo "YouTube buffer ingress and output must differ" >&2; exit 78; }
[[ "$YOUTUBE_V3_BUFFER_SECONDS" =~ ^([1-9]|10)(\.0+)?$ ]] || { echo "YOUTUBE_V3_BUFFER_SECONDS must be 1-10 seconds" >&2; exit 78; }
[[ "$YOUTUBE_V3_STARTUP_DELAY_SECONDS" =~ ^[0-9]+$ ]] || { echo "YOUTUBE_V3_STARTUP_DELAY_SECONDS must be a nonnegative integer" >&2; exit 78; }

LOCAL_BASE=${YOUTUBE_V3_BUFFERED_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=2000000&overrun_nonfatal=1&reuse=1"
TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
OVERLAY=/opt/fgbears-live/youtube-v3/youtube-v3-overlay.py
DELAY_RELAY=/opt/fgbears-live/youtube-v3/youtube-v3-delay-relay.py
PROGRESS=/run/fgbears-youtube-v3/ffmpeg-progress.log

# YouTube is intentionally 640x360@30 to preserve pacing headroom on the
# existing Oracle host. The locked 1280x720 concealment region maps exactly
# into output space as 231,52,399,235. Rumble continues to receive the full
# shared master unchanged. A bounded four-second loopback playout reserve sits
# only in front of this YouTube compositor; the overlay renderer delays its
# trigger by the same amount before applying the 15-second minimum hold.
FILTER_COMPLEX='[0:v:0]fps=30:start_time=0,settb=AVTB,setpts=N/(30*TB),scale=640:360:flags=fast_bilinear,setsar=1[base];[1:v:0]settb=AVTB,setpts=N/(5*TB)[cover];[base][cover]overlay=231:52:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v];[0:a:0]aresample=44100:async=1000:first_pts=0,asetpts=N/SR/TB[a]'

[[ -x "$OVERLAY" ]] || { echo "Missing YouTube v3 overlay renderer: $OVERLAY" >&2; exit 78; }
[[ -x "$DELAY_RELAY" ]] || { echo "Missing YouTube v3 delay relay: $DELAY_RELAY" >&2; exit 78; }

progress_sink() {
  local block="" line temporary="${PROGRESS}.partial"
  while IFS= read -r line; do
    block+="$line"$'\n'
    if [[ "$line" == progress=* ]]; then
      printf '%s' "$block" > "$temporary"
      mv -f "$temporary" "$PROGRESS"
      block=""
    fi
  done
}

# The delay relay remains a child in the same systemd cgroup. Exec keeps FFmpeg
# as the service MainPID so existing RTMPS socket and pacing monitors remain
# accurate. systemd's default control-group kill behavior cleans the relay up
# whenever the YouTube service is restarted.
YOUTUBE_V3_BUFFER_SECONDS="$YOUTUBE_V3_BUFFER_SECONDS" \
YOUTUBE_LOCAL_UDP_URL="$YOUTUBE_LOCAL_UDP_URL" \
YOUTUBE_V3_BUFFERED_UDP_URL="$YOUTUBE_V3_BUFFERED_UDP_URL" \
  "$DELAY_RELAY" &
DELAY_PID=$!
sleep 0.2
kill -0 "$DELAY_PID" 2>/dev/null || { echo "YouTube delay relay failed during startup" >&2; exit 70; }

if (( YOUTUBE_V3_STARTUP_DELAY_SECONDS > 0 )); then
  sleep "$YOUTUBE_V3_STARTUP_DELAY_SECONDS"
fi

exec env YOUTUBE_V3_BUFFER_SECONDS="$YOUTUBE_V3_BUFFER_SECONDS" ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -progress pipe:3 -stats_period 1 \
  -fflags +genpts+discardcorrupt \
  -err_detect ignore_err \
  -probesize 10000000 -analyzeduration 10000000 \
  -thread_queue_size 2048 -i "$LOCAL_INPUT" \
  -thread_queue_size 128 \
  -f rawvideo -pixel_format rgba -video_size 399x235 -framerate 5 \
  -i <(YOUTUBE_V3_BUFFER_SECONDS="$YOUTUBE_V3_BUFFER_SECONDS" "$OVERLAY") \
  -filter_complex "$FILTER_COMPLEX" \
  -map '[v]' -map '[a]' \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r 30 -fps_mode cfr -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v 1600k -maxrate 2000k -bufsize 3500k \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a 128k -ar 44100 -ac 2 \
  -max_muxing_queue_size 2048 \
  -rw_timeout 15000000 \
  -f flv -flvflags no_duration_filesize \
  "$TARGET" 3> >(progress_sink)

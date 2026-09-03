#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"

[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || { echo "YouTube input must be loopback UDP" >&2; exit 78; }

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=2000000&overrun_nonfatal=1&reuse=1"
TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"
OVERLAY=/opt/fgbears-live/youtube-v3/youtube-v3-overlay.py
PROGRESS=/run/fgbears-youtube-v3/ffmpeg-progress.log
FILTER_COMPLEX='[0:v:0]fps=30:start_time=0,settb=AVTB,setpts=N/(30*TB),setsar=1[base];[1:v:0]settb=AVTB,setpts=N/(5*TB)[cover];[base][cover]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat[v];[0:a:0]aresample=44100:async=1000:first_pts=0,asetpts=N/SR/TB[a]'

[[ -x "$OVERLAY" ]] || { echo "Missing YouTube v3 overlay renderer: $OVERLAY" >&2; exit 78; }

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

# The only acquisition/probe phase lives here. A late UDP listener may enter
# the already-running MPEG-TS stream between H.264 parameter sets and the next
# IDR, so this lightweight copy/remux stage waits for a usable stream boundary,
# drops corrupt leading material, and re-emits PAT/PMT + H.264 extra data at
# keyframes. It never decodes, renders, or re-encodes the master program.
ingest_normalizer() {
  ffmpeg \
    -hide_banner -nostdin -loglevel warning \
    -fflags +genpts+discardcorrupt \
    -err_detect ignore_err \
    -probesize 2000000 -analyzeduration 3000000 \
    -thread_queue_size 2048 -i "$LOCAL_INPUT" \
    -map 0:v:0 -map 0:a:0 \
    -c copy \
    -bsf:v dump_extra=freq=keyframe \
    -mpegts_flags +resend_headers+pat_pmt_at_frames \
    -f mpegts pipe:1 \
    2> >(sed -u 's/^/[v3-ingest] /' >&2)
}

# The compositor receives a normalized MPEG-TS stream whose program map and
# codec headers have already been established. Do not perform a second multi-
# second analysis phase here: that delay is startup acquisition time, not media
# throughput, and would be charged against FFmpeg's cumulative speed metric.
# A small probe is retained only to parse the immediately available PAT/PMT.
exec ffmpeg \
  -hide_banner -nostdin -loglevel warning \
  -progress pipe:3 -stats_period 2 \
  -fflags +genpts+discardcorrupt \
  -err_detect ignore_err \
  -probesize 131072 -analyzeduration 0 \
  -thread_queue_size 2048 -i <(ingest_normalizer) \
  -thread_queue_size 64 \
  -f rawvideo -pixel_format rgba -video_size 798x470 -framerate 5 \
  -i <("$OVERLAY") \
  -filter_complex "$FILTER_COMPLEX" \
  -map '[v]' -map '[a]' \
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p \
  -r 30 -fps_mode cfr -g 60 -keyint_min 60 -sc_threshold 0 \
  -b:v 3500k -maxrate 4000k -bufsize 7000k \
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0' \
  -c:a aac -profile:a aac_low -b:a 128k -ar 44100 -ac 2 \
  -max_muxing_queue_size 2048 \
  -rw_timeout 15000000 \
  -f flv -flvflags no_duration_filesize \
  "$TARGET" 3> >(progress_sink)

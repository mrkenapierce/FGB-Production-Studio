#!/usr/bin/env bash
# Canonical YouTube transport for FGBears Live.
#
# YouTube receives the exact shared-master H.264 video bitstream, but its audio
# is decoded and freshly encoded as a YouTube-specific AAC-LC stream. This is
# intentional: Rumble accepts the shared MPEG-TS AAC cleanly, while YouTube has
# exhibited degraded audio when that TS AAC framing/timing is copied directly
# into FLV/RTMPS. The audio resampler is used only to establish a stable YouTube
# audio clock; there is no mastering/EQ/dynamics processing in this live relay.
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939?pkt_size=1316}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${FFMPEG_LOGLEVEL:=warning}"
: "${YOUTUBE_AUDIO_BITRATE:=128k}"
: "${YOUTUBE_AUDIO_SAMPLE_RATE:=44100}"
: "${YOUTUBE_AUDIO_CHANNELS:=2}"

[[ "$YOUTUBE_STREAM_KEY" != "REPLACE_WITH_YOUTUBE_STREAM_KEY" ]] || {
  echo "Replace the placeholder YouTube stream key in $ENV_FILE" >&2
  exit 78
}
[[ "$YOUTUBE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "YOUTUBE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}
[[ "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmp://* || "$YOUTUBE_UPSTREAM_RTMP_BASE" == rtmps://* ]] || {
  echo "YOUTUBE_UPSTREAM_RTMP_BASE must be an RTMP or RTMPS URL." >&2
  exit 78
}
[[ "$YOUTUBE_AUDIO_BITRATE" == "128k" ]] || {
  echo "YOUTUBE_AUDIO_BITRATE must remain 128k for the canonical YouTube stereo profile." >&2
  exit 78
}
[[ "$YOUTUBE_AUDIO_SAMPLE_RATE" == "44100" ]] || {
  echo "YOUTUBE_AUDIO_SAMPLE_RATE must remain 44100 for the canonical YouTube stereo profile." >&2
  exit 78
}
[[ "$YOUTUBE_AUDIO_CHANNELS" == "2" ]] || {
  echo "YOUTUBE_AUDIO_CHANNELS must remain 2 for the canonical YouTube stereo profile." >&2
  exit 78
}

LOCAL_BASE=${YOUTUBE_LOCAL_UDP_URL%%\?*}
LOCAL_INPUT="${LOCAL_BASE}?fifo_size=1000000&overrun_nonfatal=1&reuse=1"
UPSTREAM_TARGET="${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}"

# Preserve the shared video bitstream. Rebuild only the YouTube audio elementary
# stream so AAC framing and timestamps are generated specifically for this
# RTMPS session. aresample async corrects timestamp discontinuities without
# applying tonal or loudness DSP.
echo "Starting canonical YouTube relay: H.264 copy + freshly clocked AAC-LC ${YOUTUBE_AUDIO_SAMPLE_RATE} Hz stereo ${YOUTUBE_AUDIO_BITRATE}." >&2
exec ffmpeg \
  -hide_banner -nostdin -loglevel "$FFMPEG_LOGLEVEL" \
  -fflags +genpts+discardcorrupt -probesize 10000000 -analyzeduration 10000000 \
  -i "$LOCAL_INPUT" \
  -map 0:v:0 -map 0:a:0 \
  -c:v copy \
  -c:a aac -profile:a aac_low -b:a "$YOUTUBE_AUDIO_BITRATE" \
  -ar "$YOUTUBE_AUDIO_SAMPLE_RATE" -ac "$YOUTUBE_AUDIO_CHANNELS" \
  -af "aresample=${YOUTUBE_AUDIO_SAMPLE_RATE}:async=1:first_pts=0" \
  -f flv -flvflags no_duration_filesize \
  "$UPSTREAM_TARGET"

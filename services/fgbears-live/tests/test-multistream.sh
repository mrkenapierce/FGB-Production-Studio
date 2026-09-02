#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/youtube-relay.sh" "$ROOT/bin/rumble-relay.sh" "$ROOT/bin/configure-rumble.sh" "$ROOT/bin/install.sh" "$ROOT/bin/healthcheck.sh" "$ROOT/bin/stream-status.sh"; do
  bash -n "$script"
done

for retired in \
  "$ROOT/bin/x-relay.sh" "$ROOT/bin/instagram-relay.sh" \
  "$ROOT/bin/configure-x.sh" "$ROOT/bin/configure-instagram.sh" \
  "$ROOT/systemd/fgbears-x-relay.service" "$ROOT/systemd/fgbears-x-start.service" "$ROOT/systemd/fgbears-x-stop.service" "$ROOT/systemd/fgbears-x-start.timer" "$ROOT/systemd/fgbears-x-stop.timer" \
  "$ROOT/systemd/fgbears-instagram-relay.service" "$ROOT/systemd/fgbears-instagram-start.service" "$ROOT/systemd/fgbears-instagram-stop.service" "$ROOT/systemd/fgbears-instagram-start.timer" "$ROOT/systemd/fgbears-instagram-stop.timer" \
  "$ROOT/bin/facebook-relay.sh" "$ROOT/bin/configure-facebook.sh"; do
  test ! -e "$retired"
done

if grep -R --exclude=finalize-youtube-only.py -nE 'X_LOCAL_UDP_URL|X_RELAY_ENABLED|X_STREAM_ENABLED|INSTAGRAM_LOCAL_UDP_URL|INSTAGRAM_RELAY_ENABLED|FACEBOOK_LOCAL_UDP_URL|fgbears-(x|instagram|facebook)-relay|X local mirror|Instagram local mirror|Facebook local mirror' "$ROOT/bin" "$ROOT/config" "$ROOT/systemd"; then
  echo 'Retired social simulcast protocol remains in active FGB livestream code.' >&2
  exit 1
fi

# The shared master produces two isolated local MPEG-TS mirrors. Rumble keeps an
# unchanged copy/remux. YouTube may consume its mirror through the exact-box
# compositor; the legacy relay remains fallback-only and copies H.264 while
# rebuilding AAC at the native 48 kHz rate solely for RTMP clock continuity.
grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq 'isolated YouTube and Rumble local UDP mirrors' "$ROOT/bin/start-stream.sh"
grep -Fq 'rtmp://rtmp.rumble.com/live' "$ROOT/bin/rumble-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
grep -Fq -- '-c:v copy' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-c:a aac' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'YOUTUBE_AUDIO_SAMPLE_RATE=48000' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'aresample=${YOUTUBE_AUDIO_SAMPLE_RATE}:async=1:first_pts=0' "$ROOT/bin/youtube-relay.sh"
if grep -Fq 'YOUTUBE_TRIVIA_OVERLAY' "$ROOT/bin/youtube-relay.sh" || grep -Fq -- '-c:v libx264' "$ROOT/bin/youtube-relay.sh"; then
  echo 'Fallback YouTube relay must remain video-copy plus transparent AAC clock rebuild.' >&2
  exit 1
fi
if grep -Fq 'YOUTUBE_TRIVIA_OVERLAY' "$ROOT/bin/rumble-relay.sh"; then
  echo 'YouTube-only trivia overlay leaked into the Rumble relay.' >&2
  exit 1
fi

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -hide_banner -loglevel error \
    -f lavfi -i testsrc2=size=320x180:rate=24 \
    -f lavfi -i sine=frequency=440:sample_rate=48000 \
    -t 0.5 -map 0:v -map 1:a \
    -c:v libx264 -preset ultrafast -g 48 -c:a aac -b:a 128k \
    -f tee -use_fifo 1 -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
    "[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/youtube-local.ts|[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/rumble-local.ts"
  test -s "$TMP/youtube-local.ts"
  test -s "$TMP/rumble-local.ts"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=h264$'
fi

echo 'FGBears transport invariants: isolated master mirrors, unchanged Rumble copy/remux, and native-48k YouTube fallback transport.'

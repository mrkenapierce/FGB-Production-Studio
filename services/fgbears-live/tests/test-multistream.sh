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

grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq 'isolated YouTube and Rumble local UDP mirrors' "$ROOT/bin/start-stream.sh"
grep -Fq 'rtmp://rtmp.rumble.com/live' "$ROOT/bin/rumble-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
grep -Fq 'YOUTUBE_TRIVIA_OVERLAY_PORT:=8790' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'http://127.0.0.1:${YOUTUBE_TRIVIA_OVERLAY_PORT}/overlay.rgba' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-c:v libx264' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-c:a copy' "$ROOT/bin/youtube-relay.sh"
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
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=h264$'
fi

echo 'FGBears transport provides a YouTube-only trivia overlay and an untouched Rumble copy-remux relay.'

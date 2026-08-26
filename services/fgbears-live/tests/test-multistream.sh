#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/youtube-relay.sh" "$ROOT/bin/x-relay.sh" "$ROOT/bin/instagram-relay.sh" "$ROOT/bin/configure-x.sh" "$ROOT/bin/configure-instagram.sh" "$ROOT/bin/install.sh" "$ROOT/bin/healthcheck.sh" "$ROOT/bin/stream-status.sh"; do
  bash -n "$script"
done

for removed in "$ROOT/bin/facebook-relay.sh" "$ROOT/bin/configure-facebook.sh" "$ROOT/systemd/fgbears-facebook-relay.service" "$ROOT/systemd/fgbears-facebook-start.timer" "$ROOT/systemd/fgbears-facebook-stop.timer"; do
  test ! -e "$removed"
done

if grep -R -nE 'FACEBOOK_|fgbears-facebook|Facebook local mirror|live-api-s\.facebook\.com' "$ROOT/bin" "$ROOT/config" "$ROOT/systemd"; then
  echo 'Retired protocol remnants remain in active FGB livestream code.' >&2
  exit 1
fi

grep -Fq 'YOUTUBE_LOCAL_UDP_URL' "$ROOT/bin/start-stream.sh"
grep -Fq '[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq '[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${X_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq '[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${INSTAGRAM_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq 'for platform in x instagram' "$ROOT/bin/install.sh"
grep -Fq 'reconcile_social_relay x X_RELAY_ENABLED' "$ROOT/bin/healthcheck.sh"
grep -Fq 'reconcile_social_relay instagram INSTAGRAM_RELAY_ENABLED' "$ROOT/bin/healthcheck.sh"

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -hide_banner -loglevel error \
    -f lavfi -i testsrc2=size=320x180:rate=24 \
    -f lavfi -i sine=frequency=440:sample_rate=48000 \
    -t 0.5 -map 0:v -map 1:a \
    -c:v libx264 -preset ultrafast -g 48 -c:a aac -b:a 128k \
    -f tee -use_fifo 1 -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
    "[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/youtube-local.ts|[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/x-local.ts|[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/instagram-local.ts"
  for output in "$TMP/youtube-local.ts" "$TMP/x-local.ts" "$TMP/instagram-local.ts"; do
    test -s "$output"
    ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=aac$'
    ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=h264$'
  done
fi

echo 'FGBears active transport contains YouTube/X/Instagram only.'

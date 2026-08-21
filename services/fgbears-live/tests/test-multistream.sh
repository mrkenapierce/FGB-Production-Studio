#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/youtube-relay.sh" "$ROOT/bin/x-relay.sh" "$ROOT/bin/facebook-relay.sh" "$ROOT/bin/instagram-relay.sh" "$ROOT/bin/configure-x.sh" "$ROOT/bin/configure-facebook.sh" "$ROOT/bin/configure-instagram.sh" "$ROOT/bin/install.sh" "$ROOT/bin/healthcheck.sh" "$ROOT/bin/stream-status.sh"; do
  bash -n "$script"
done

grep -q '^X_ACCOUNT_HANDLE=@epic501c3$' "$ROOT/config/stream.env.example"
grep -q '^X_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^X_RELAY_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^X_SCHEDULE_START=09:00$' "$ROOT/config/stream.env.example"
grep -q '^X_SCHEDULE_STOP=17:00$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_RELAY_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -Fq 'FACEBOOK_LOCAL_UDP_URL=udp://127.0.0.1:1936?pkt_size=1316' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_RTMP_BASE=rtmps://live-api-s.facebook.com:443/rtmp/$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_SCHEDULE_TIMEZONE=America/Chicago$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_SCHEDULE_START=09:00$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_SCHEDULE_STOP=17:00$' "$ROOT/config/stream.env.example"
grep -q '^INSTAGRAM_RELAY_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^INSTAGRAM_SCHEDULE_START=09:00$' "$ROOT/config/stream.env.example"
grep -q '^INSTAGRAM_SCHEDULE_STOP=17:00$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_LOCAL_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_UPSTREAM_RTMP_BASE=rtmps://a.rtmps.youtube.com/live2$' "$ROOT/config/stream.env.example"

grep -Fq 'FACEBOOK_LOCAL_UDP_URL' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '[f=mpegts:onfail=ignore]${FACEBOOK_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq '[f=mpegts:onfail=ignore]${X_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq '[f=mpegts:onfail=ignore]${INSTAGRAM_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq 'Facebook local mirror' "$ROOT/bin/start-stream.sh"
if grep -Fq 'live-api-s.facebook.com' "$ROOT/bin/start-stream.sh" || grep -Fq 'FACEBOOK_STREAM_KEY' "$ROOT/bin/start-stream.sh"; then
  echo 'The primary encoder must never know the Meta endpoint or Facebook stream key.' >&2
  exit 1
fi

grep -Fq 'for platform in x facebook instagram' "$ROOT/bin/install.sh"
grep -Fq 'for unit in relay.service start.service stop.service start.timer stop.timer' "$ROOT/bin/install.sh"
grep -Fq 'FACEBOOK_STREAM_ENABLED": "0"' "$ROOT/bin/install.sh"
grep -Fq 'FACEBOOK_RELAY_ENABLED' "$ROOT/bin/configure-facebook.sh"
if grep -Fq 'systemctl restart fgbears-live.service' "$ROOT/bin/configure-facebook.sh"; then
  echo 'Facebook scheduling must never restart the primary encoder.' >&2
  exit 1
fi
if grep -Fq 'systemctl restart fgbears-youtube-relay.service' "$ROOT/bin/configure-facebook.sh"; then
  echo 'Facebook scheduling must never restart the dedicated YouTube relay.' >&2
  exit 1
fi

if grep -Fq 'FACEBOOK_' "$ROOT/bin/youtube-relay.sh" || grep -Fq -- '-f tee' "$ROOT/bin/youtube-relay.sh"; then
  echo 'The YouTube relay must remain a dedicated YouTube-only FLV copy-remux process.' >&2
  exit 1
fi
grep -Fq -- '-listen 1' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-f flv -flvflags no_duration_filesize' "$ROOT/bin/youtube-relay.sh"

grep -Fq 'FACEBOOK_LOCAL_UDP_URL' "$ROOT/bin/facebook-relay.sh"
# shellcheck disable=SC2016
grep -Fq -- '-i "$FACEBOOK_LOCAL_UDP_URL"' "$ROOT/bin/facebook-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/facebook-relay.sh"
grep -Fq 'FACEBOOK_RTMP_BASE' "$ROOT/bin/facebook-relay.sh"
if grep -Fq -- '-listen 1' "$ROOT/bin/facebook-relay.sh"; then
  echo 'Facebook sidecar should consume the UDP mirror rather than host an RTMP listener.' >&2
  exit 1
fi

for platform in x facebook instagram; do
  grep -Fq 'OnCalendar=*-*-* 09:00:00 America/Chicago' "$ROOT/systemd/fgbears-$platform-start.timer"
  grep -Fq 'OnCalendar=*-*-* 17:00:00 America/Chicago' "$ROOT/systemd/fgbears-$platform-stop.timer"
  grep -Fq 'Persistent=true' "$ROOT/systemd/fgbears-$platform-start.timer"
  grep -Fq 'Persistent=true' "$ROOT/systemd/fgbears-$platform-stop.timer"
done
grep -Fq 'Persistent=true' "$ROOT/systemd/fgbears-facebook-start.timer"
grep -Fq 'Persistent=true' "$ROOT/systemd/fgbears-facebook-stop.timer"

grep -Fq 'reconcile_social_relay x X_RELAY_ENABLED' "$ROOT/bin/healthcheck.sh"
grep -Fq 'reconcile_social_relay facebook FACEBOOK_RELAY_ENABLED' "$ROOT/bin/healthcheck.sh"
grep -Fq 'reconcile_social_relay instagram INSTAGRAM_RELAY_ENABLED' "$ROOT/bin/healthcheck.sh"

grep -Fq 'Wants=network-online.target fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"
if grep -Fq 'Requires=fgbears-facebook-relay.service' "$ROOT/systemd/fgbears-live.service"; then
  echo 'Facebook must not be a hard lifecycle dependency of the primary encoder.' >&2
  exit 1
fi
if grep -Fq 'fgbears-live.service' "$ROOT/systemd/fgbears-facebook-relay.service"; then
  echo 'Facebook sidecar must not require or control the primary service.' >&2
  exit 1
fi

if grep -Eq 'REPLACE_WITH_(X|FACEBOOK)_STREAM_KEY' "$ROOT/config/stream.env.example"; then
  echo 'Never commit secondary-platform credential placeholders that could be mistaken for configured secrets.' >&2
  exit 1
fi

# Generate one encoded program, then model the exact packet topology without any
# external network: local FLV to YouTube and MPEG-TS to all social sidecars.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 0.5 -map 0:v -map 1:a \
  -c:v libx264 -preset ultrafast -g 48 \
  -c:a aac -b:a 128k \
  -f tee -use_fifo 1 \
  -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
  "[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/youtube-local.flv|[f=mpegts:onfail=ignore]$TMP/x-local.ts|[f=mpegts:onfail=ignore]$TMP/facebook-local.ts|[f=mpegts:onfail=ignore]$TMP/instagram-local.ts"

ffmpeg -hide_banner -loglevel error -i "$TMP/youtube-local.flv" -map 0:v:0 -map 0:a:0 -c copy -f flv -flvflags no_duration_filesize "$TMP/youtube-upstream.flv"
ffmpeg -hide_banner -loglevel error -i "$TMP/x-local.ts" -map 0:v:0 -map 0:a:0 -c copy -f flv -flvflags no_duration_filesize "$TMP/x-upstream.flv"
ffmpeg -hide_banner -loglevel error -i "$TMP/facebook-local.ts" -map 0:v:0 -map 0:a:0 -c copy -f flv -flvflags no_duration_filesize "$TMP/facebook-upstream.flv"
ffmpeg -hide_banner -loglevel error -i "$TMP/instagram-local.ts" -map 0:v:0 -map 0:a:0 \
  -vf 'scale=720:-2:flags=lanczos,pad=720:1280:0:(oh-ih)/2:black,format=yuv420p' \
  -c:v libx264 -preset ultrafast -c:a aac -f flv -flvflags no_duration_filesize "$TMP/instagram-upstream.flv"

for output in "$TMP/youtube-local.flv" "$TMP/youtube-upstream.flv" "$TMP/x-local.ts" "$TMP/x-upstream.flv" "$TMP/facebook-local.ts" "$TMP/facebook-upstream.flv" "$TMP/instagram-local.ts" "$TMP/instagram-upstream.flv"; do
  test -s "$output"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=h264$'
done

echo 'FGBears scheduled isolated X, Facebook, and Instagram sidecar tests passed.'

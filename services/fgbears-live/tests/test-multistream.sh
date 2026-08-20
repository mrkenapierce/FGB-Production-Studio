#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/youtube-relay.sh" "$ROOT/bin/facebook-relay.sh" "$ROOT/bin/configure-x.sh" "$ROOT/bin/configure-facebook.sh" "$ROOT/bin/install.sh"; do
  bash -n "$script"
done

grep -q '^X_ACCOUNT_HANDLE=@epic501c3$' "$ROOT/config/stream.env.example"
grep -q '^X_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_RELAY_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_LOCAL_RTMP_BASE=rtmp://127.0.0.1:1936/live$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_RTMP_BASE=rtmps://live-api-s.facebook.com:443/rtmp/$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_LOCAL_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_UPSTREAM_RTMP_BASE=rtmps://a.rtmps.youtube.com/live2$' "$ROOT/config/stream.env.example"

grep -Fq 'fgbears-facebook-relay' "$ROOT/bin/install.sh"
grep -Fq 'fgbears-facebook-relay.service' "$ROOT/bin/install.sh"
grep -Fq 'FACEBOOK_STREAM_ENABLED": "0"' "$ROOT/bin/install.sh"
grep -Fq 'FACEBOOK_RELAY_ENABLED' "$ROOT/bin/configure-facebook.sh"
grep -Fq 'systemctl restart fgbears-youtube-relay.service' "$ROOT/bin/configure-facebook.sh"
if grep -Fq 'systemctl restart fgbears-live.service' "$ROOT/bin/configure-facebook.sh"; then
  echo 'Facebook configuration must never restart the primary encoder.' >&2
  exit 1
fi

grep -Fq 'FACEBOOK_LOCAL_RTMP_BASE' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'fgb-facebook' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'onfail=ignore' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-listen 1' "$ROOT/bin/facebook-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/facebook-relay.sh"
grep -Fq 'FACEBOOK_RTMP_BASE' "$ROOT/bin/facebook-relay.sh"

grep -Fq 'Wants=network-online.target fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"
grep -Fq 'FACEBOOK_STREAM_ENABLED=(1|true|yes|on)' "$ROOT/systemd/fgbears-live.service"
if grep -Fq 'Requires=fgbears-facebook-relay.service' "$ROOT/systemd/fgbears-live.service"; then
  echo 'Facebook must not be a lifecycle dependency of the primary encoder.' >&2
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

# Generate one encoded H.264/AAC sample, then prove both relay stages use stream
# copy only. This mirrors production without making any external connections.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 0.5 -map 0:v -map 1:a \
  -c:v libx264 -preset ultrafast -g 48 \
  -c:a aac -b:a 128k \
  -f flv "$TMP/primary.flv"

ffmpeg -hide_banner -loglevel error \
  -i "$TMP/primary.flv" -map 0:v:0 -map 0:a:0 -c copy \
  -f tee -use_fifo 1 \
  -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
  "[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/youtube.flv|[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/facebook-local.flv"

ffmpeg -hide_banner -loglevel error \
  -i "$TMP/facebook-local.flv" -map 0:v:0 -map 0:a:0 -c copy \
  -f flv -flvflags no_duration_filesize "$TMP/facebook-upstream.flv"

for output in "$TMP/youtube.flv" "$TMP/facebook-local.flv" "$TMP/facebook-upstream.flv"; do
  test -s "$output"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=h264$'
done

echo 'FGBears isolated Facebook copy-remux sidecar tests passed.'

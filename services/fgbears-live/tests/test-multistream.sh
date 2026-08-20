#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

bash -n "$ROOT/bin/start-stream.sh"
bash -n "$ROOT/bin/youtube-relay.sh"
bash -n "$ROOT/bin/configure-x.sh"
bash -n "$ROOT/bin/install.sh"

grep -q '^X_ACCOUNT_HANDLE=@epic501c3$' "$ROOT/config/stream.env.example"
grep -q '^X_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^X_RTMP_BASE=$' "$ROOT/config/stream.env.example"
grep -q '^X_STREAM_KEY=$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_STREAM_ENABLED=0$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_RTMP_BASE=rtmps://live-api-s.facebook.com:443/rtmp/$' "$ROOT/config/stream.env.example"
grep -q '^FACEBOOK_STREAM_KEY=$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_LOCAL_RTMP_BASE=rtmp://127.0.0.1:1935/live$' "$ROOT/config/stream.env.example"
grep -q '^YOUTUBE_UPSTREAM_RTMP_BASE=rtmps://a.rtmps.youtube.com/live2$' "$ROOT/config/stream.env.example"
grep -Fq "TARGET_X_ACCOUNT='@epic501c3'" "$ROOT/bin/configure-x.sh"
grep -Fq 'fgbears-configure-x' "$ROOT/bin/install.sh"
grep -Fq 'fgbears-youtube-relay' "$ROOT/bin/install.sh"
grep -Fq 'fgbears-youtube-relay.service' "$ROOT/bin/install.sh"
grep -Fq 'missing_packages=()' "$ROOT/bin/install.sh"
grep -Fq 'skipping apt' "$ROOT/bin/install.sh"
grep -Fq 'Acquire::Retries=3' "$ROOT/bin/install.sh"
grep -Fq -- '-c:a aac -b:a 128k -ar 48000 -ac 2' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq 'TEE_TARGETS="[f=flv:flvflags=no_duration_filesize:onfail=ignore]${YOUTUBE_TARGET}"' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
if grep -Fq 'onfail=abort]${YOUTUBE_TARGET}' "$ROOT/bin/start-stream.sh"; then
  echo 'The YouTube relay leg must recover independently of the primary encoder.' >&2
  exit 1
fi
grep -Fq 'X Live Studio' "$ROOT/bin/start-stream.sh"
grep -Fq 'Facebook Live Producer' "$ROOT/bin/start-stream.sh"
grep -Fq 'FACEBOOK_STREAM_ACTIVE' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-listen 1' "$ROOT/bin/youtube-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'YOUTUBE_UPSTREAM_RTMP_BASE' "$ROOT/bin/youtube-relay.sh"
grep -Fq 'Wants=network-online.target fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"
if grep -Fq 'Requires=fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"; then
  echo 'The primary encoder must not stop when the YouTube relay restarts.' >&2
  exit 1
fi

if grep -Eq 'REPLACE_WITH_(X|FACEBOOK)_STREAM_KEY' "$ROOT/config/stream.env.example"; then
  echo 'Never commit secondary-platform credential placeholders that could be mistaken for configured secrets.' >&2
  exit 1
fi

# Prove the primary encode can fan identical H.264/AAC packets to a recoverable
# local YouTube-relay input plus secondary FLV outputs. This remains one encode.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=48000 \
  -t 0.5 -map 0:v -map 1:a \
  -c:v libx264 -preset ultrafast -g 48 \
  -c:a aac -b:a 128k \
  -f tee -use_fifo 1 \
  -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
  "[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/youtube-relay-input.flv|[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/x.flv|[f=flv:flvflags=no_duration_filesize:onfail=ignore]$TMP/facebook.flv"

for output in "$TMP/youtube-relay-input.flv" "$TMP/x.flv" "$TMP/facebook.flv"; do
  test -s "$output"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$output" | grep -q '^codec_name=h264$'
done

# Prove the YouTube leg is remuxed with stream copy rather than re-encoded.
ffmpeg -hide_banner -loglevel error \
  -i "$TMP/youtube-relay-input.flv" \
  -map 0:v:0 -map 0:a:0 -c copy \
  -f flv -flvflags no_duration_filesize \
  "$TMP/youtube-upstream.flv"

test -s "$TMP/youtube-upstream.flv"
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-upstream.flv" | grep -q '^codec_name=aac$'
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-upstream.flv" | grep -q '^codec_name=h264$'

echo 'FGBears resilient single-encode plus YouTube copy-remux relay tests passed.'

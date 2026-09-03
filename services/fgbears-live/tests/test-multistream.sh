#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

for script in \
  "$ROOT/bin/start-stream.sh" \
  "$ROOT/bin/rumble-relay.sh" \
  "$ROOT/bin/configure-rumble.sh" \
  "$ROOT/bin/install.sh" \
  "$ROOT/bin/healthcheck.sh" \
  "$ROOT/bin/stream-status.sh" \
  "$ROOT/youtube-v2/run-youtube-v2.sh" \
  "$ROOT/youtube-v2/verify-youtube-v2.sh"
do
  bash -n "$script"
done

# The shared FFmpeg process encodes once, then mirrors the same MPEG-TS program
# to isolated loopback ports for YouTube and Rumble.
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
grep -Fq 'YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939' "$ROOT/bin/start-stream.sh"
grep -Fq 'RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
if [[ $(grep -Fc -- '-c:v libx264' "$ROOT/bin/start-stream.sh") -ne 1 ]]; then
  echo 'Shared program must contain exactly one video encode.' >&2; exit 1
fi

# Rumble receives the shared pixels/audio unchanged.
grep -Fq 'RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940' "$ROOT/bin/rumble-relay.sh"
grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
if grep -Eq 'libx264|overlay=|youtube-v2|creative' "$ROOT/bin/rumble-relay.sh"; then
  echo 'Rumble must remain a copy-remux with no destination compositor.' >&2; exit 1
fi

# Only YouTube v2 re-encodes video, because different pixels require exactly one
# post-split compositor. It consumes the existing 1939 mirror and one RGBA layer.
grep -Fq 'YOUTUBE_LOCAL_UDP_URL:=udp://127.0.0.1:1939' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq 'youtube-v2-overlay.py' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq 'pixel_format rgba' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq 'overlay=462:104' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq -- '-c:v libx264' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq -- '-c:a aac' "$ROOT/youtube-v2/run-youtube-v2.sh"

# There is no active second YouTube relay/router implementation.
for path in \
  "$ROOT/bin/youtube-relay.sh" \
  "$ROOT/bin/youtube-relay-legacy.sh" \
  "$ROOT/bin/youtube-stream-router.py" \
  "$ROOT/bin/youtube-stream-router-v5.py" \
  "$ROOT/bin/youtube-trivia-overlay.py" \
  "$ROOT/bin/youtube-offhost-compositor.sh"
do
  test ! -e "$path"
done

# Verify FFmpeg tee syntax independently without external network targets.
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc=size=160x90:rate=10:duration=1 \
  -f lavfi -i sine=frequency=440:sample_rate=44100:duration=1 \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset ultrafast -g 20 -c:a aac \
  -f tee -use_fifo 1 \
  "[f=mpegts]$TMP/a.ts|[f=mpegts]$TMP/b.ts"
test -s "$TMP/a.ts"
test -s "$TMP/b.ts"

python3 - "$TMP/a.ts" "$TMP/b.ts" <<'PY'
import subprocess, sys
for path in sys.argv[1:]:
    out=subprocess.check_output([
        'ffprobe','-v','error','-show_entries','stream=codec_type,codec_name',
        '-of','compact=p=0:nk=1',path
    ], text=True)
    assert 'h264|video' in out or 'video|h264' in out, out
    assert 'aac|audio' in out or 'audio|aac' in out, out
PY

echo 'Multistream architecture passed: one shared encode, Rumble copy-remux, one YouTube-v2 difference compositor.'

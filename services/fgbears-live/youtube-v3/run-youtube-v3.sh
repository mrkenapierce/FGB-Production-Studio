#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required}"
: "${YOUTUBE_UPSTREAM_RTMP_BASE:=rtmps://a.rtmps.youtube.com/live2}"
: "${YOUTUBE_V3_RUNTIME_DIR:=/run/fgbears-youtube-v3}"
: "${YOUTUBE_V3_PERIOD_SECONDS:=1200}"
: "${YOUTUBE_V3_PREARM_SECONDS:=8}"
: "${YOUTUBE_V3_GUARD_SECONDS:=300}"
: "${YOUTUBE_V3_LIVE_START_INDEX:=-2}"
: "${YOUTUBE_V3_TARGET:=}"

ROOT="$YOUTUBE_V3_RUNTIME_DIR/source"
PLAYLIST="$ROOT/live.m3u8"
COVER=/opt/fgbears-live/youtube-v3/youtube-trivia-cover.png
PROGRESS="$YOUTUBE_V3_RUNTIME_DIR/output.progress"
START_FILE="$YOUTUBE_V3_RUNTIME_DIR/output.start_epoch"
[[ -r "$COVER" ]] || { echo "Missing cover: $COVER" >&2; exit 66; }

for _ in $(seq 1 60); do
  [[ -s "$PLAYLIST" ]] && grep -q '^#EXT-X-PROGRAM-DATE-TIME:' "$PLAYLIST" && break
  sleep 0.5
done
[[ -s "$PLAYLIST" ]] || { echo "v3 source playlist unavailable" >&2; exit 69; }

START_EPOCH=$(python3 - "$PLAYLIST" "$YOUTUBE_V3_LIVE_START_INDEX" <<'PY'
from datetime import datetime
import sys
p=sys.argv[1]; idx=int(sys.argv[2])
vals=[]
for line in open(p, encoding='utf-8'):
    if line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
        s=line.split(':',1)[1].strip().replace('Z','+00:00')
        vals.append(datetime.fromisoformat(s).timestamp())
if not vals: raise SystemExit(2)
pos=idx if idx < 0 else idx
try: print(f'{vals[pos]:.6f}')
except IndexError: print(f'{vals[-1]:.6f}')
PY
)
printf '%s\n' "$START_EPOCH" > "$START_FILE"
OFFSET=$(python3 - "$START_EPOCH" "$YOUTUBE_V3_PERIOD_SECONDS" <<'PY'
import sys
print(f'{float(sys.argv[1]) % float(sys.argv[2]):.6f}')
PY
)

PERIOD=$YOUTUBE_V3_PERIOD_SECONDS
PREARM=$YOUTUBE_V3_PREARM_SECONDS
GUARD=$YOUTUBE_V3_GUARD_SECONDS
FILTER="[0:v:0]setpts=PTS-STARTPTS,fps=30,setsar=1[base];[1:v:0]format=rgba[cover];[base][cover]overlay=462:104:format=auto:shortest=0:repeatlast=1:eof_action=repeat:enable='lt(mod(t+${OFFSET},${PERIOD}),${GUARD})+gte(mod(t+${OFFSET},${PERIOD}),${PERIOD}-${PREARM})'[v];[0:a:0]aresample=48000:async=1:first_pts=0,asetpts=PTS-STARTPTS[a]"
TARGET=${YOUTUBE_V3_TARGET:-${YOUTUBE_UPSTREAM_RTMP_BASE%/}/${YOUTUBE_STREAM_KEY}}

progress_sink() {
  local block='' line tmp="${PROGRESS}.partial"
  while IFS= read -r line; do
    block+="$line"$'\n'
    if [[ "$line" == progress=* ]]; then
      printf '%s' "$block" > "$tmp"
      mv -f "$tmp" "$PROGRESS"
      block=''
    fi
  done
}
rm -f "$PROGRESS" "${PROGRESS}.partial"

COMMON=(
  -hide_banner -nostdin -loglevel warning
  -re -live_start_index "$YOUTUBE_V3_LIVE_START_INDEX" -i "$PLAYLIST"
  -loop 1 -framerate 1 -i "$COVER"
  -filter_complex "$FILTER"
  -map '[v]' -map '[a]'
  -c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -pix_fmt yuv420p
  -r 30 -fps_mode cfr -g 60 -keyint_min 60 -sc_threshold 0
  -b:v 3500k -maxrate 4000k -bufsize 7000k
  -threads 1 -x264-params 'repeat-headers=1:keyint=60:min-keyint=60:scenecut=0'
  -c:a aac -profile:a aac_low -b:a 128k -ar 48000 -ac 2
  -max_muxing_queue_size 2048
  -progress pipe:3 -stats_period 2
)

if [[ "$TARGET" == /* ]]; then
  exec 3> >(progress_sink)
  exec ffmpeg "${COMMON[@]}" -y -f flv -flvflags no_duration_filesize "$TARGET" 3>&3
else
  exec 3> >(progress_sink)
  exec ffmpeg "${COMMON[@]}" -rw_timeout 15000000 -f flv -flvflags no_duration_filesize "$TARGET" 3>&3
fi

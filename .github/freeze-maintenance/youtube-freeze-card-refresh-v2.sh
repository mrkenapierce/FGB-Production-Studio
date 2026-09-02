#!/usr/bin/env bash
set -Eeuo pipefail

# Low-cost YouTube freeze-card refresher for the existing hot-reload packet router.
# Captures a single non-question program frame and replaces ONLY the reconciled
# trivia rectangle (x=480,y=200,w=640,h=360). It never continuously re-encodes.
#
# Safety contract:
# - authoritative routing payload and exact mask geometry are required;
# - phase=question or youtubeMaskActive=true is always rejected;
# - ad/transition flags do NOT block capture because the trivia rectangle is fully
#   replaced and the current master frame outside that rectangle is intentionally
#   frozen for the brief question interval;
# - stale state is accepted only away from :00/:20/:40 anchor minutes;
# - routing is checked again after encode; a newly active question discards the card;
# - atomic rename means the hot-reload router sees only complete H.264 assets.

ROUTING_URL="${FGB_STREAM_ROUTING_URL:-https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing}"
BASE_INPUT_URL="${FGB_YOUTUBE_FREEZE_INPUT_URL:-${YOUTUBE_LOCAL_UDP_URL:-udp://127.0.0.1:1939?pkt_size=1316}}"
if [[ "$BASE_INPUT_URL" == udp://* ]]; then
  INPUT_URL="$BASE_INPUT_URL"
  [[ "$INPUT_URL" == *reuse=1* ]] || INPUT_URL+="${INPUT_URL#*\?}" && true
  # Rebuild deterministically to avoid shell precedence surprises and duplicate reuse.
  if [[ "$BASE_INPUT_URL" == *"?"* ]]; then
    INPUT_URL="$BASE_INPUT_URL"
    [[ "$INPUT_URL" == *"reuse=1"* ]] || INPUT_URL="${INPUT_URL}&reuse=1"
    [[ "$INPUT_URL" == *"fifo_size="* ]] || INPUT_URL="${INPUT_URL}&fifo_size=1000000"
    [[ "$INPUT_URL" == *"overrun_nonfatal="* ]] || INPUT_URL="${INPUT_URL}&overrun_nonfatal=1"
  else
    INPUT_URL="${BASE_INPUT_URL}?reuse=1&fifo_size=1000000&overrun_nonfatal=1"
  fi
else
  INPUT_URL="$BASE_INPUT_URL"
fi

OUT_DIR="${FGB_YOUTUBE_FREEZE_CARD_DIR:-/var/lib/fgbears-live}"
OUT_FILE="${FGB_YOUTUBE_FREEZE_CARD_H264:-${OUT_DIR}/youtube-freeze-card.h264}"
LOCK_FILE="${OUT_DIR}/youtube-freeze-card.lock"
STATUS_FILE="${OUT_DIR}/youtube-freeze-card.status"
MASK_X=480
MASK_Y=200
MASK_W=640
MASK_H=360
ATTEMPTS="${FGB_YOUTUBE_FREEZE_ATTEMPTS:-30}"
RETRY_SECONDS="${FGB_YOUTUBE_FREEZE_RETRY_SECONDS:-2}"

mkdir -p "$OUT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "freeze-card refresh already running; exiting" >&2
  exit 0
fi

routing_safe() {
  python3 - "$ROUTING_URL" <<'PY'
import json, sys, time, urllib.parse, urllib.request
url = sys.argv[1]
parts = urllib.parse.urlsplit(url)
q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
q.append(("_ts", str(time.time_ns())))
url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), parts.fragment))
req = urllib.request.Request(url, headers={
    "Accept":"application/json", "Cache-Control":"no-cache", "Pragma":"no-cache",
    "User-Agent":"FGBears-YouTube-FreezeCard/2.0",
})
try:
    with urllib.request.urlopen(req, timeout=3) as r:
        payload = json.loads(r.read().decode("utf-8"))
except Exception as exc:
    print(f"unsafe: routing fetch failed: {exc}", file=sys.stderr); raise SystemExit(2)
if not isinstance(payload, dict):
    print("unsafe: routing payload not object", file=sys.stderr); raise SystemExit(2)
trivia = payload.get("trivia")
if not isinstance(trivia, dict):
    print("unsafe: missing trivia object", file=sys.stderr); raise SystemExit(2)
phase = trivia.get("phase")
if phase == "question" or trivia.get("youtubeMaskActive") is True:
    print(f"unsafe: active question phase={phase!r}", file=sys.stderr); raise SystemExit(2)
region = trivia.get("maskRegion")
expected = {
    "x":480, "y":200, "width":640, "height":360,
    "coordinateSpace":"pixels", "referenceWidth":1280, "referenceHeight":720,
}
if not isinstance(region, dict) or any(region.get(k) != v for k,v in expected.items()):
    print(f"unsafe: unexpected maskRegion={region!r}", file=sys.stderr); raise SystemExit(2)
if trivia.get("stale") is True:
    minute = time.localtime().tm_min
    cycle_minute = minute % 20
    if not (1 <= cycle_minute <= 18):
        print(f"unsafe: stale state too close to trivia anchor minute={minute:02d}", file=sys.stderr)
        raise SystemExit(2)
print(f"safe phase={phase!r} stale={trivia.get('stale') is True} ads={trivia.get('adsVisible') is True}")
PY
}

safe=0
for ((i=1; i<=ATTEMPTS; i++)); do
  if routing_safe; then
    # Require the non-question state to remain true across a short debounce.
    sleep 1
    if routing_safe; then
      safe=1
      break
    fi
  fi
  (( i < ATTEMPTS )) && sleep "$RETRY_SECONDS"
done
if (( safe == 0 )); then
  echo "No non-question capture window found; retaining previous card" >&2
  printf 'result=skipped reason=no-nonquestion-window at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

work=$(mktemp -d "${OUT_DIR}/.youtube-freeze-card.XXXXXX")
trap 'rm -rf "$work"' EXIT
frame="$work/program.png"
candidate="$work/card.h264"

nice -n 19 ionice -c3 timeout 12 ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts -probesize 3000000 -analyzeduration 3000000 \
  -i "$INPUT_URL" -map 0:v:0 -frames:v 1 -y "$frame"
test -s "$frame"

FILTER="drawbox=x=${MASK_X}:y=${MASK_Y}:w=${MASK_W}:h=${MASK_H}:color=0x07101F@1:t=fill,\
drawbox=x=${MASK_X}:y=${MASK_Y}:w=${MASK_W}:h=${MASK_H}:color=0xC83803@1:t=5,\
drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='YOUTUBE VIEWERS':fontcolor=white:fontsize=22:x=${MASK_X}+(${MASK_W}-text_w)/2:y=${MASK_Y}+55,\
drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='TRIVIA IS LIVE ON RUMBLE':fontcolor=0xF2B134:fontsize=42:x=${MASK_X}+(${MASK_W}-text_w)/2:y=${MASK_Y}+125,\
drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='Watch and play on Rumble':fontcolor=white:fontsize=28:x=${MASK_X}+(${MASK_W}-text_w)/2:y=${MASK_Y}+205,\
drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='epiccontentcreatorgrants.org':fontcolor=0xD5D9E2:fontsize=20:x=${MASK_X}+(${MASK_W}-text_w)/2:y=${MASK_Y}+263"

nice -n 19 ionice -c3 ffmpeg -hide_banner -nostdin -loglevel warning \
  -loop 1 -i "$frame" -vf "$FILTER" -t 1 -r 30 \
  -c:v libx264 -preset ultrafast -tune stillimage -profile:v baseline -level:v 3.1 \
  -pix_fmt yuv420p -g 30 -keyint_min 30 -sc_threshold 0 -threads 1 \
  -x264-params 'aud=1:repeat-headers=1:keyint=30:min-keyint=30:scenecut=0' \
  -f h264 -y "$candidate"
test -s "$candidate"

probe=$(ffprobe -v error -f h264 -select_streams v:0 \
  -show_entries stream=codec_name,width,height,pix_fmt -of csv=p=0 "$candidate")
[[ "$probe" == "h264,1280,720,yuv420p" ]]

if ! routing_safe; then
  echo "Question became active during generation; discarding candidate" >&2
  printf 'result=discarded reason=question-became-active at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

chmod 0644 "$candidate"
mv -f "$candidate" "${OUT_FILE}.new"
mv -f "${OUT_FILE}.new" "$OUT_FILE"
printf 'result=updated at=%s bytes=%s geometry=480,200,640,360 mode=nonquestion-freeze-v2\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(stat -c %s "$OUT_FILE")" >"$STATUS_FILE.tmp"
mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
echo "Freeze-box v2 card updated: $OUT_FILE"

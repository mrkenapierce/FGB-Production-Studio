#!/usr/bin/env bash
set -Eeuo pipefail

# Generate a low-cost, pre-encoded YouTube trivia replacement card from a recent
# live program frame. Only the verified question/answer rectangle is replaced.
# This runs BETWEEN trivia rounds; it never continuously encodes the stream.
#
# Safety properties:
# - authoritative routing state must be fresh and outside a question/ad break
#   both BEFORE capture and AFTER encode;
# - geometry must exactly match the reconciled 480,200 640x360 contract;
# - output is written by atomic rename, so the live router never sees a partial
#   H.264 file;
# - any failure leaves the previous known-good card untouched.

ROUTING_URL="${FGB_STREAM_ROUTING_URL:-https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing}"
INPUT_URL="${YOUTUBE_LOCAL_UDP_URL:-udp://127.0.0.1:1939?fifo_size=1000000&overrun_nonfatal=1&reuse=1}"
OUT_DIR="${FGB_YOUTUBE_FREEZE_CARD_DIR:-/var/lib/fgbears-live}"
OUT_FILE="${FGB_YOUTUBE_FREEZE_CARD_H264:-${OUT_DIR}/youtube-freeze-card.h264}"
LOCK_FILE="${OUT_DIR}/youtube-freeze-card.lock"
STATUS_FILE="${OUT_DIR}/youtube-freeze-card.status"
MASK_X=480
MASK_Y=200
MASK_W=640
MASK_H=360
ATTEMPTS="${FGB_YOUTUBE_FREEZE_ATTEMPTS:-6}"
RETRY_SECONDS="${FGB_YOUTUBE_FREEZE_RETRY_SECONDS:-10}"

mkdir -p "$OUT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "freeze-card refresh already running; exiting" >&2
  exit 0
fi

safe_state() {
  python3 - "$ROUTING_URL" <<'PY'
import json, sys, time, urllib.parse, urllib.request
url = sys.argv[1]
parts = urllib.parse.urlsplit(url)
q = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
q.append(("_ts", str(time.time_ns())))
url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(q), parts.fragment))
req = urllib.request.Request(url, headers={
    "Accept":"application/json",
    "Cache-Control":"no-cache",
    "Pragma":"no-cache",
    "User-Agent":"FGBears-YouTube-FreezeCard/1.0",
})
try:
    with urllib.request.urlopen(req, timeout=3) as r:
        payload = json.loads(r.read().decode("utf-8"))
except Exception as exc:
    print(f"unsafe: routing fetch failed: {exc}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(payload, dict):
    print("unsafe: routing payload not object", file=sys.stderr); raise SystemExit(2)
trivia = payload.get("trivia")
if not isinstance(trivia, dict):
    print("unsafe: missing trivia object", file=sys.stderr); raise SystemExit(2)
phase = trivia.get("phase")
if trivia.get("stale") is True:
    print("unsafe: trivia state stale", file=sys.stderr); raise SystemExit(2)
if phase == "question" or trivia.get("youtubeMaskActive") is True:
    print(f"unsafe: active question phase={phase!r}", file=sys.stderr); raise SystemExit(2)
# Be conservative across both root- and trivia-level ad-state variants.
for obj_name, obj in (("root", payload), ("trivia", trivia)):
    for key in ("adsVisible", "isAdBreak", "adBreakActive"):
        if obj.get(key) is True:
            print(f"unsafe: {obj_name}.{key}=true", file=sys.stderr); raise SystemExit(2)
region = trivia.get("maskRegion")
expected = {
    "x":480, "y":200, "width":640, "height":360,
    "coordinateSpace":"pixels", "referenceWidth":1280, "referenceHeight":720,
}
if not isinstance(region, dict) or any(region.get(k) != v for k,v in expected.items()):
    print(f"unsafe: unexpected maskRegion={region!r}", file=sys.stderr); raise SystemExit(2)
print(f"safe phase={phase!r}")
PY
}

safe=0
for ((i=1; i<=ATTEMPTS; i++)); do
  if safe_state; then
    safe=1
    break
  fi
  if (( i < ATTEMPTS )); then
    sleep "$RETRY_SECONDS"
  fi
done
if (( safe == 0 )); then
  echo "No safe refresh window found; retaining previous card" >&2
  printf 'result=skipped reason=no-safe-window at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

work=$(mktemp -d "${OUT_DIR}/.youtube-freeze-card.XXXXXX")
trap 'rm -rf "$work"' EXIT
frame="$work/program.png"
candidate="$work/card.h264"

# Attach to the already-encoded local MPEG-TS branch only long enough to decode
# one still frame. UDP reuse is intentional and was production-benchmarked.
nice -n 19 ionice -c3 timeout 12 ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts -probesize 3000000 -analyzeduration 3000000 \
  -i "$INPUT_URL" -map 0:v:0 -frames:v 1 -y "$frame"
test -s "$frame"

# Encode one second of a static 1280x720 H.264 card. The source frame remains
# visible everywhere except the exact 640x360 trivia question/answer rectangle.
# AUD + repeated SPS/PPS headers are required by the packet router's parser.
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

# Validate dimensions/codec and make sure the router can parse AUD/IDR units.
probe=$(ffprobe -v error -f h264 -select_streams v:0 \
  -show_entries stream=codec_name,profile,width,height,pix_fmt,level \
  -of json "$candidate")
python3 - "$probe" <<'PY'
import json, sys
p=json.loads(sys.argv[1]); s=(p.get("streams") or [{}])[0]
assert s.get("codec_name")=="h264", s
assert s.get("width")==1280 and s.get("height")==720, s
assert s.get("pix_fmt")=="yuv420p", s
PY

# Re-check routing AFTER the ~4-second capture/encode. If trivia or an ad began
# during generation, discard this candidate rather than publishing a frame from
# an unsafe moment.
if ! safe_state; then
  echo "Routing changed during generation; discarding candidate" >&2
  printf 'result=discarded reason=state-changed at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

chmod 0644 "$candidate"
# Atomic same-filesystem publication.
mv -f "$candidate" "${OUT_FILE}.new"
mv -f "${OUT_FILE}.new" "$OUT_FILE"
printf 'result=updated at=%s bytes=%s geometry=480,200,640,360\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(stat -c %s "$OUT_FILE")" >"$STATUS_FILE.tmp"
mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
echo "Freeze-box card updated: $OUT_FILE"

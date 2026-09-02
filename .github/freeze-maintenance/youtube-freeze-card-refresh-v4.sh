#!/usr/bin/env bash
set -Eeuo pipefail

# Efficiency v4 production refresher.
# Captures one safe non-question program frame, generates the EXISTING locked
# 1280x720 YouTube→Rumble card with its canonical builder (QR included), scales
# that complete card as one immutable image into production AD_PANEL_BOX, then
# encodes a one-second H.264 still for the packet router. No live video encode.

ROUTING_URL="${FGB_STREAM_ROUTING_URL:-https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing}"
BASE_INPUT_URL="${FGB_YOUTUBE_FREEZE_INPUT_URL:-${YOUTUBE_LOCAL_UDP_URL:-udp://127.0.0.1:1939?pkt_size=1316}}"
BUILDER="${FGB_YOUTUBE_EXACT_CARD_BUILDER:-/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py}"
COMPOSER="${FGB_YOUTUBE_EXACT_CARD_COMPOSER:-/opt/fgbears-live/tools/compose-exact-youtube-card.py}"
OUT_DIR="${FGB_YOUTUBE_FREEZE_CARD_DIR:-/var/lib/fgbears-live}"
OUT_FILE="${FGB_YOUTUBE_FREEZE_CARD_H264:-${OUT_DIR}/youtube-freeze-card.h264}"
LOCK_FILE="${OUT_DIR}/youtube-freeze-card.lock"
STATUS_FILE="${OUT_DIR}/youtube-freeze-card.status"
ATTEMPTS="${FGB_YOUTUBE_FREEZE_ATTEMPTS:-30}"
RETRY_SECONDS="${FGB_YOUTUBE_FREEZE_RETRY_SECONDS:-2}"

# Production AD_PANEL_BOX=(462,104)-(1260,574); news ends at y=103 and crawl
# begins at y=574. The exact 16:9 source card fits as 798x449 at x=462,y=114.
PANEL_X=462
PANEL_Y=104
PANEL_W=798
PANEL_H=470
CARD_W=798
CARD_H=449
CARD_X=462
CARD_Y=114

if [[ "$BASE_INPUT_URL" == udp://* ]]; then
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

[[ -r "$BUILDER" ]] || { echo "Missing exact locked-card builder: $BUILDER" >&2; exit 66; }
[[ -r "$COMPOSER" ]] || { echo "Missing exact whole-card composer: $COMPOSER" >&2; exit 66; }
python3 -c 'import PIL, qrcode' >/dev/null
mkdir -p "$OUT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "exact-card refresh already running; exiting" >&2
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
    "User-Agent":"FGBears-YouTube-ExactCard/4.0",
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
expected = {
    "x":462, "y":104, "width":798, "height":470,
    "coordinateSpace":"pixels", "referenceWidth":1280, "referenceHeight":720,
}
region = trivia.get("maskRegion")
if not isinstance(region, dict) or any(region.get(k) != v for k,v in expected.items()):
    print(f"unsafe: unexpected production maskRegion={region!r}", file=sys.stderr); raise SystemExit(2)
if trivia.get("stale") is True:
    minute = time.localtime().tm_min
    cycle_minute = minute % 20
    if not (1 <= cycle_minute <= 18):
        print(f"unsafe: stale state too close to trivia anchor minute={minute:02d}", file=sys.stderr)
        raise SystemExit(2)
print(f"safe phase={phase!r} stale={trivia.get('stale') is True}")
PY
}

safe=0
for ((i=1; i<=ATTEMPTS; i++)); do
  if routing_safe; then
    sleep 1
    if routing_safe; then safe=1; break; fi
  fi
  (( i < ATTEMPTS )) && sleep "$RETRY_SECONDS"
done
if (( safe == 0 )); then
  echo "No safe non-question capture window found; retaining previous card" >&2
  printf 'result=skipped reason=no-safe-window at=%s mode=exact-card-v4\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

work=$(mktemp -d "${OUT_DIR}/.youtube-exact-card.XXXXXX")
trap 'rm -rf "$work"' EXIT
frame="$work/program.png"
source_card="$work/locked-card.png"
composite="$work/composite.png"
candidate="$work/card.h264"
metadata="$work/compose.json"

nice -n 19 ionice -c3 timeout 12 ffmpeg -hide_banner -nostdin -loglevel warning \
  -fflags +genpts -probesize 3000000 -analyzeduration 3000000 \
  -i "$INPUT_URL" -map 0:v:0 -frames:v 1 -y "$frame"
test -s "$frame"

# This is the canonical locked-template builder already present in the project.
# It contains the exact QR, copy, coordinates, colors, bars, border and fonts.
python3 "$BUILDER" "$source_card" >/dev/null
test -s "$source_card"

python3 "$COMPOSER" "$frame" "$source_card" "$composite" >"$metadata"
grep -Fq '"mode": "exact-locked-template-whole-card"' "$metadata"
grep -Fq '"width": 798' "$metadata"
grep -Fq '"height": 449' "$metadata"
test -s "$composite"

# Static encode only; video selector continues packet-level switching and audio
# remains on the existing continuous repaired YouTube path.
nice -n 19 ionice -c3 ffmpeg -hide_banner -nostdin -loglevel warning \
  -loop 1 -i "$composite" -t 1 -r 30 \
  -c:v libx264 -preset ultrafast -tune stillimage -profile:v baseline -level:v 3.1 \
  -pix_fmt yuv420p -g 30 -keyint_min 30 -sc_threshold 0 -threads 1 \
  -x264-params 'aud=1:repeat-headers=1:keyint=30:min-keyint=30:scenecut=0' \
  -f h264 -y "$candidate"
test -s "$candidate"
probe=$(ffprobe -v error -f h264 -select_streams v:0 \
  -show_entries stream=codec_name,width,height,pix_fmt -of csv=p=0 "$candidate")
[[ "$probe" == "h264,1280,720,yuv420p" ]]

# A question starting during generation invalidates the candidate.
if ! routing_safe; then
  echo "Question became active during exact-card generation; discarding candidate" >&2
  printf 'result=discarded reason=question-became-active at=%s mode=exact-card-v4\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATUS_FILE.tmp"
  mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
  exit 0
fi

source_sha=$(sha256sum "$source_card" | awk '{print $1}')
chmod 0644 "$candidate"
mv -f "$candidate" "${OUT_FILE}.new"
mv -f "${OUT_FILE}.new" "$OUT_FILE"
printf 'result=updated at=%s bytes=%s panel=%s,%s,%s,%s card=%s,%s,%s,%s source=locked-yt_rumble_trivia_redirect source_sha256=%s mode=exact-card-v4\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(stat -c %s "$OUT_FILE")" \
  "$PANEL_X" "$PANEL_Y" "$PANEL_W" "$PANEL_H" \
  "$CARD_X" "$CARD_Y" "$CARD_W" "$CARD_H" "$source_sha" >"$STATUS_FILE.tmp"
mv -f "$STATUS_FILE.tmp" "$STATUS_FILE"
echo "Exact locked-template freeze card updated: $OUT_FILE"

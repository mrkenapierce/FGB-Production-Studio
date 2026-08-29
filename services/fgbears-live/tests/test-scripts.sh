#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
OVERLAY_PID=""
CRAWL_PID=""
cleanup() {
  for pid in "$OVERLAY_PID" "$CRAWL_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

for script in "$ROOT"/bin/*.sh; do
  bash -n "$script"
done
python3 -m py_compile "$ROOT/bin/ad-overlay.py" "$ROOT/bin/ad-overlay-smart.py" "$ROOT/bin/game_overlay.py" "$ROOT/bin/crawl-overlay.py" "$ROOT/bin/bears-news-feed.py" "$ROOT/bin/youtube-trivia-overlay.py"
python3 "$ROOT/tests/test-game-overlay.py"
python3 "$ROOT/tests/test-youtube-trivia-overlay.py"
python3 - "$ROOT/bin/crawl-overlay.py" <<'PY'
import runpy
import sys

module = runpy.run_path(sys.argv[1])
sequence = module["CrawlSequence"]()
value = {"active": True, "messages": ["STANDINGS", "LEADERBOARD", "HOW TO PLAY"]}
message, _ = sequence.select(value, 100.0)
assert message == "STANDINGS"

# A live-data refresh must not replace or resize the segment already on screen.
refreshed = {"active": True, "messages": ["UPDATED STANDINGS", "UPDATED LEADERBOARD", "HOW TO PLAY"]}
message, _ = sequence.select(refreshed, 101.0)
assert message == "STANDINGS"
assert not sequence.advance_if_complete(-99, 100, 102.0)
assert sequence.advance_if_complete(-100, 100, 103.0)
message, _ = sequence.select(refreshed, 103.0)
assert message == "UPDATED LEADERBOARD"
assert sequence.advance_if_complete(-100, 100, 104.0)
message, _ = sequence.select(refreshed, 104.0)
assert message == "HOW TO PLAY"
PY

# These are intentionally literal shell expressions from start-stream.sh.
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${AD_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${CRAWL_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq -- '-f mpjpeg -i "http://127.0.0.1:${BEARS_NEWS_OVERLAY_PORT}/overlay.mjpg"' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-preset ultrafast' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-progress pipe:3' "$ROOT/bin/start-stream.sh"
if grep -Fq -- '-af ' "$ROOT/bin/start-stream.sh"; then
  echo 'The production live chain must preserve mastered episode audio without live DSP.' >&2
  exit 1
fi
grep -Fq -- '-c:a copy' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
if grep -Fq 'rtmp://127.0.0.1:1935' "$ROOT/bin/start-stream.sh"; then
  echo 'The primary encoder must not depend on the retired local RTMP YouTube listener.' >&2
  exit 1
fi
grep -Fq 'onfail=ignore' "$ROOT/bin/start-stream.sh"
grep -Fq 'StartLimitBurst=3' "$ROOT/systemd/fgbears-live.service"
grep -Fq 'Restart=on-failure' "$ROOT/systemd/fgbears-live.service"
grep -Fq 'Wants=network-online.target fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"
if grep -Fq 'Requires=fgbears-youtube-relay.service' "$ROOT/systemd/fgbears-live.service"; then
  echo 'The YouTube relay must not be a hard lifecycle dependency of the primary encoder.' >&2
  exit 1
fi

if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then
  echo 'A real stream.env file must never be committed.' >&2
  exit 1
fi

cat > "$TMP/feed.json" <<'JSON'
{"kind":"house","sponsors":[{"businessName":"FGB","imageUrl":null,"promoMessage":"Bear Down","website":"https://epiccontentcreatorgrants.org/epic-media","durationSeconds":7}]}
JSON
cat > "$TMP/game.json" <<'JSON'
{"visible":false,"presentationMode":"crawl_only","adsEnabled":false}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" GAME_SCREEN_FEED_FILE="$TMP/game.json" CRAWL_RUNTIME_DIR="$TMP/runtime" AD_FRAME_FILE="$TMP/runtime/ad-frame.jpg" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay-smart.py" >"$TMP/ad-overlay.log" 2>&1 &
OVERLAY_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18787/healthz >"$TMP/ad-health.json" && break
  sleep 0.1
done
if ! jq -e '.ok == true' "$TMP/ad-health.json" >/dev/null; then
  cat "$TMP/ad-overlay.log" >&2 || true
  exit 1
fi
curl --silent --fail http://127.0.0.1:18787/frame.jpg -o "$TMP/ad-frame.jpg"
python3 - "$TMP/ad-frame.jpg" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]); im.load(); assert im.size == (1280, 720), im.size
PY
kill "$OVERLAY_PID"; wait "$OVERLAY_PID" 2>/dev/null || true; OVERLAY_PID=""

# The game feed can replace the central panel without changing the renderer port
# or FFmpeg input. No external network is required in this test.
cat > "$TMP/game.json" <<'JSON'
{"visible":true,"gameId":"test-game","presentationMode":"alternate_game_ads","adsEnabled":false,"title":"ZIP SHOWDOWN","matchup":"61108 VS 61107","currentPrize":"$25","phase":"question","questionNumber":1,"questionCount":1,"prompt":"WHO WAS NICKNAMED SWEETNESS?","choices":[{"key":"A","text":"DICK BUTKUS"},{"key":"B","text":"WALTER PAYTON"}],"participants":12,"standings":[{"zip":"61108","score":4,"players":7}],"playPath":"/fgb/play","gameScreenSeconds":20,"adsPerBreak":1,"keepTriviaCrawlDuringAds":true,"allowPaidAds":true,"allowHouseAds":true}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" GAME_SCREEN_FEED_FILE="$TMP/game.json" CRAWL_RUNTIME_DIR="$TMP/runtime" AD_FRAME_FILE="$TMP/runtime/game-frame.jpg" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay-smart.py" >"$TMP/game-overlay.log" 2>&1 &
OVERLAY_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18787/healthz >/dev/null && break
  sleep 0.1
done
if ! curl --silent --fail http://127.0.0.1:18787/frame.jpg -o "$TMP/game-frame.jpg"; then
  cat "$TMP/game-overlay.log" >&2 || true
  exit 1
fi
python3 - "$TMP/game-frame.jpg" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]); im.load(); assert im.size == (1280, 720), im.size
# A game screen uses the dark central panel rather than the normal white ad card.
pixel = im.getpixel((500, 200))
assert sum(pixel) < 250, pixel
PY
kill "$OVERLAY_PID"; wait "$OVERLAY_PID" 2>/dev/null || true; OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"FGB LIVE","message":"legacy first message","messages":[{"enabled":true,"text":"MESSAGE ONE"},{"enabled":true,"text":"MESSAGE TWO"},{"enabled":true,"text":"MESSAGE THREE"},{"enabled":true,"text":"MESSAGE FOUR"},{"enabled":true,"text":"MESSAGE FIVE"}],"separator":"•","speed":"normal","updatedAt":"2026-08-25T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_RUNTIME_DIR="$TMP/runtime" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl-overlay.log" 2>&1 &
CRAWL_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18788/healthz >"$TMP/crawl-health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .active == true and .messageCount == 5' "$TMP/crawl-health.json" >/dev/null
python3 - "$TMP/runtime/crawl-message.txt" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding='utf-8')
expected = ['MESSAGE ONE', 'MESSAGE TWO', 'MESSAGE THREE', 'MESSAGE FOUR', 'MESSAGE FIVE']
positions = [text.index(message) for message in expected]
assert positions == sorted(positions), (positions, text)
assert text.count('•') == 4, text
assert 'LEGACY FIRST MESSAGE' not in text, text
PY
curl --silent --fail http://127.0.0.1:18788/frame.jpg -o "$TMP/crawl-frame.jpg"
python3 - "$TMP/crawl-frame.jpg" <<'PY'
from PIL import Image
import sys
im = Image.open(sys.argv[1]); im.load(); assert im.size == (1280, 139), im.size
PY
kill "$CRAWL_PID"; wait "$CRAWL_PID" 2>/dev/null || true; CRAWL_PID=""

mkdir -p "$TMP/media"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=640x360:r=24:d=0.5 \
  -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.5 \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$TMP/source.mp4"
MEDIA_DIR="$TMP/media" bash "$ROOT/bin/normalize-library.sh" "$TMP/source.mp4" "$TMP/media/episode-01.mp4"
bash "$ROOT/bin/validate-media.sh" "$TMP/media"
MEDIA_DIR="$TMP/media" PLAYLIST_FILE="$TMP/playlist.ffconcat" bash "$ROOT/bin/rebuild-playlist.sh"
grep -q 'episode-01.mp4' "$TMP/playlist.ffconcat"

echo 'FGBears Live integration tests passed.'

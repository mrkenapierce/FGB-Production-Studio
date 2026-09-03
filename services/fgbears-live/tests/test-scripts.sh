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

for script in "$ROOT"/bin/*.sh "$ROOT"/youtube-v2/*.sh; do
  bash -n "$script"
done
python3 -m py_compile \
  "$ROOT/bin/ad-overlay.py" \
  "$ROOT/bin/ad-overlay-smart.py" \
  "$ROOT/bin/game_overlay.py" \
  "$ROOT/bin/crawl-overlay.py" \
  "$ROOT/bin/bears-news-feed.py" \
  "$ROOT/youtube-v2/youtube-v2-overlay.py"
python3 "$ROOT/tests/test-game-overlay.py"

# Validate the sole destination-specific renderer without a network call.
YOUTUBE_REDIRECT_CARD_BUILDER="$ROOT/tools/build-youtube-rumble-trivia-card.py" \
python3 - "$ROOT/youtube-v2/youtube-v2-overlay.py" "$TMP" <<'PY'
import importlib.util
import sys
from pathlib import Path
from PIL import Image

path=Path(sys.argv[1]); tmp=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('v2overlay', path)
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
region={"x":462,"y":104,"width":798,"height":470,
        "coordinateSpace":"pixels","referenceWidth":1280,"referenceHeight":720}
def payload(key='yt_rumble_trivia_redirect', **change):
    trivia={"stale":False,"phase":"question","adsVisible":False,"isAdBreak":False,
            "adBreakActive":False,"youtubeMaskActive":True,"youtubeCreativeKey":key,
            "maskRegion":region,
            "presentation":{"rumble":{"rendersRealQuestion":True},
              "youtube":{"rendersRealQuestion":False,
                "maskedRegion":{"x":462,"y":104,"width":798,"height":470},
                "creativeKey":key,"sourceTemplateKey":key,
                "presentationMode":"full_creative_scaled"}}}
    trivia.update(change)
    return {"trivia":trivia}

state=m.validate(payload())
assert m.should_cover(state)
assert len(m.build_frame(state['_validatedCreativeKey'])) == 798*470*4
for change in ({"stale":True},{"phase":"revealed"},{"adsVisible":True},
               {"isAdBreak":True},{"adBreakActive":True},{"youtubeMaskActive":False}):
    assert not m.should_cover(m.validate(payload(**change)))
creative_dir=tmp/'creatives'; creative_dir.mkdir()
m.CREATIVE_DIR=creative_dir; m._FRAME_CACHE.clear()
Image.new('RGBA',(320,180),(255,0,0,128)).save(creative_dir/'sponsor_a.png')
assert 'sponsor_a' in m.available_creative_keys()
assert len(m.build_frame('sponsor_a')) == 798*470*4
try:
    m.build_frame('not_installed')
except FileNotFoundError:
    pass
else:
    raise AssertionError('unapproved creative must fail closed')
PY

python3 - "$ROOT/bin/crawl-overlay.py" <<'PY'
import runpy, sys
module=runpy.run_path(sys.argv[1])
sequence=module['CrawlSequence']()
value={"active":True,"messages":["STANDINGS","LEADERBOARD","HOW TO PLAY"]}
message,_=sequence.select(value,100.0); assert message == 'STANDINGS'
refreshed={"active":True,"messages":["UPDATED STANDINGS","UPDATED LEADERBOARD","HOW TO PLAY"]}
message,_=sequence.select(refreshed,101.0); assert message == 'STANDINGS'
assert not sequence.advance_if_complete(-99,100,102.0)
assert sequence.advance_if_complete(-100,100,103.0)
message,_=sequence.select(refreshed,103.0); assert message == 'UPDATED LEADERBOARD'
PY

# Common program is rendered once and mirrored locally.
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
# shellcheck disable=SC2016
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-c:a copy' "$ROOT/bin/start-stream.sh"
if grep -Fq -- '-af ' "$ROOT/bin/start-stream.sh"; then
  echo 'Shared program must preserve mastered audio without live DSP.' >&2; exit 1
fi
if grep -Fq 'rtmp://127.0.0.1:1935' "$ROOT/bin/start-stream.sh"; then
  echo 'Shared program must not depend on retired local RTMP YouTube relay.' >&2; exit 1
fi

# Rumble remains the canonical copy-remux destination.
grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
if grep -Eq 'overlay=|libx264|youtube-v2' "$ROOT/bin/rumble-relay.sh"; then
  echo 'Rumble must not gain a destination renderer.' >&2; exit 1
fi

# YouTube v2 alone owns destination-specific pixels.
grep -Fq 'overlay=462:104' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq -- '-c:v libx264' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq 'youtube-v2-overlay.py' "$ROOT/youtube-v2/run-youtube-v2.sh"
grep -Fq 'Rumble must remain the canonical live-question presentation' "$ROOT/youtube-v2/youtube-v2-overlay.py"

grep -Fq 'FGB_YOUTUBE_PACKET_ROUTER_ENABLE=0' "$ROOT/config/stream.env.example"
grep -Fq 'systemctl enable fgbears-youtube-v2.service' "$ROOT/bin/install.sh"
if grep -Eq 'install .*youtube-relay|enable .*youtube-relay|restart .*youtube-relay' "$ROOT/bin/install.sh"; then
  echo 'Installer can reactivate retired YouTube relay.' >&2; exit 1
fi
if grep -Eq 'install .*youtube-audio-watchdog|enable .*youtube-audio-watchdog|restart .*youtube-audio-watchdog' "$ROOT/bin/install.sh"; then
  echo 'Installer can reactivate retired YouTube watchdog.' >&2; exit 1
fi

grep -Fq 'Wants=network-online.target' "$ROOT/systemd/fgbears-live.service"
if grep -Eq 'youtube-relay|youtube-router|lovable-compositor' "$ROOT/systemd/fgbears-live.service"; then
  echo 'Shared master service contains legacy destination dependency.' >&2; exit 1
fi
grep -Fq 'YOUTUBE_SERVICE=${YOUTUBE_SERVICE:-fgbears-youtube-v2.service}' "$ROOT/bin/healthcheck.sh"
grep -Fq 'recover_youtube_v2' "$ROOT/bin/healthcheck.sh"
if grep -Eq 'YOUTUBE_RELAY_SERVICE|recover_youtube_relay|fgbears-youtube-relay.service' "$ROOT/bin/healthcheck.sh"; then
  echo 'Healthcheck contains retired YouTube relay recovery.' >&2; exit 1
fi

for path in \
  "$ROOT/bin/youtube-relay.sh" \
  "$ROOT/bin/youtube-stream-router.py" \
  "$ROOT/bin/youtube-trivia-overlay.py" \
  "$ROOT/systemd/fgbears-youtube-relay.service" \
  "$ROOT/systemd/fgbears-youtube-audio-watchdog.service"
do
  test ! -e "$path"
done
test -d "$ROOT/quarantine/youtube-legacy"
if find "$ROOT/quarantine/youtube-legacy" -type f -perm /111 -print -quit | grep -q .; then
  echo 'Quarantined legacy file is executable.' >&2; exit 1
fi

if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then
  echo 'A real stream.env file must never be committed.' >&2; exit 1
fi

# Smoke-test common ad/crawl HTTP renderers.
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
jq -e '.ok == true' "$TMP/ad-health.json" >/dev/null
curl --silent --fail http://127.0.0.1:18787/frame.jpg -o "$TMP/ad-frame.jpg"
python3 - "$TMP/ad-frame.jpg" <<'PY'
from PIL import Image
import sys
im=Image.open(sys.argv[1]); im.load(); assert im.size == (1280,720)
PY
kill "$OVERLAY_PID"; wait "$OVERLAY_PID" 2>/dev/null || true; OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"FGB LIVE","message":"legacy first message","messages":[{"enabled":true,"text":"MESSAGE ONE"},{"enabled":true,"text":"MESSAGE TWO"},{"enabled":true,"text":"MESSAGE THREE"}],"separator":"•","speed":"normal","updatedAt":"2026-08-25T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_RUNTIME_DIR="$TMP/runtime" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl-overlay.log" 2>&1 &
CRAWL_PID=$!
for _ in {1..40}; do
  curl --silent --fail --max-time 1 http://127.0.0.1:18788/healthz >"$TMP/crawl-health.json" && break
  sleep 0.1
done
jq -e '.ok == true and .active == true and .messageCount == 3' "$TMP/crawl-health.json" >/dev/null
kill "$CRAWL_PID"; wait "$CRAWL_PID" 2>/dev/null || true; CRAWL_PID=""

# Media normalization remains unchanged.
mkdir -p "$TMP/media"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i color=c=black:s=640x360:r=24:d=0.5 \
  -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.5 \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$TMP/source.mp4"
MEDIA_DIR="$TMP/media" bash "$ROOT/bin/normalize-library.sh" "$TMP/source.mp4" "$TMP/media/episode-01.mp4"
bash "$ROOT/bin/validate-media.sh" "$TMP/media"
MEDIA_DIR="$TMP/media" PLAYLIST_FILE="$TMP/playlist.ffconcat" bash "$ROOT/bin/rebuild-playlist.sh"
grep -q 'episode-01.mp4' "$TMP/playlist.ffconcat"

echo 'FGBears Live integration tests passed: minimal v2 architecture.'

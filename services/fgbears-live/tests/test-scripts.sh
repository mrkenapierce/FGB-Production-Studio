#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
OVERLAY_PID=""; CRAWL_PID=""
cleanup(){
  for pid in "$OVERLAY_PID" "$CRAWL_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

for script in "$ROOT"/bin/*.sh "$ROOT"/youtube-v3/*.sh; do bash -n "$script"; done
python3 -m py_compile "$ROOT/bin/ad-overlay.py" "$ROOT/bin/ad-overlay-smart.py" "$ROOT/bin/game_overlay.py" "$ROOT/bin/crawl-overlay.py" "$ROOT/bin/bears-news-feed.py" "$ROOT/youtube-v3/youtube-v3-overlay.py" "$ROOT/youtube-v3/lovable-state-cache.py" "$ROOT/youtube-v3/build-creatives.py"
python3 "$ROOT/tests/test-game-overlay.py"
python3 "$ROOT/youtube-v3/build-creatives.py"

YOUTUBE_V3_CREATIVE_DIR="$ROOT/youtube-v3/creatives" python3 - "$ROOT/youtube-v3/youtube-v3-overlay.py" <<'PY'
import importlib.util, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
path=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location('v3overlay',path)
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
assert 'urllib' not in path.read_text(), 'renderer must contain no HTTP client'
region={"x":462,"y":104,"width":798,"height":470,"coordinateSpace":"pixels","referenceWidth":1280,"referenceHeight":720}
def iso(seconds): return (datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat().replace('+00:00','Z')
def payload(key='yt_rumble_trivia_redirect', **change):
    trivia={"active":True,"stale":False,"phase":"question","gameVisible":True,"youtubeRedirectRequired":True}
    ad={"active":False,"adsVisible":False,"isAdBreak":False}
    diff={"enabled":True,"creativeKey":key,"reason":"question_phase","region":region,"presentationMode":"full_creative_scaled"}
    for k,v in change.items():
        if k.startswith('trivia_'): trivia[k[7:]]=v
        elif k.startswith('ad_'): ad[k[3:]]=v
        else: diff[k]=v
    return {"schemaVersion":"fgb-stream-state/v1","generatedAt":iso(-1),"validUntil":iso(4),"revision":"rtest",
            "presentation":{"adBreak":ad,"trivia":trivia,"routing":{"rumble":{"rendersRealQuestion":True},"youtube":{"differenceLayer":diff}},
                            "overlay":{},"crawl":{},"news":{},"schedule":{},"mask":{"region":region}}}
pres,key=m.validate(payload()); assert m.should_cover(pres,key); assert len(m.build_frame(key)) == 798*470*4
for changed in (payload(trivia_stale=True),payload(trivia_phase='revealed'),payload(trivia_gameVisible=False),payload(trivia_youtubeRedirectRequired=False),payload(ad_active=True),payload(enabled=False)):
    pres,key=m.validate(changed); assert not m.should_cover(pres,key)
expired=payload(); expired['validUntil']=iso(-1)
try: m.validate(expired)
except ValueError: pass
else: raise AssertionError('expired state must fail transparent')
try: m.build_frame('not_installed')
except (ValueError, FileNotFoundError): pass
else: raise AssertionError('unapproved creative must fail closed')
print('YOUTUBE_V3_RENDERER_TEST=PASS contract=fgb-stream-state/v1 local_state_only=yes')
PY

# Shared program is still encoded once and mirrored to YouTube/Rumble loopback.
grep -Fq -- '-f tee -use_fifo 1' "$ROOT/bin/start-stream.sh"
grep -Fq '${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:' "$ROOT/bin/start-stream.sh"
grep -Fq '${RUMBLE_LOCAL_UDP_URL}' "$ROOT/bin/start-stream.sh"
grep -Fq -- '-c:a copy' "$ROOT/bin/start-stream.sh"
! grep -Fq -- '-af ' "$ROOT/bin/start-stream.sh"

# Rumble remains copy/remux only.
grep -Fq -- '-c copy' "$ROOT/bin/rumble-relay.sh"
! grep -Eq 'overlay=|libx264|youtube-v3|creative' "$ROOT/bin/rumble-relay.sh"

# Sole destination compositor is v3; control and media clocks are separated.
grep -Fq 'overlay=462:104' "$ROOT/youtube-v3/run-youtube-v3.sh"
grep -Fq -- '-framerate 5' "$ROOT/youtube-v3/run-youtube-v3.sh"
grep -Fq -- '-progress pipe:3' "$ROOT/youtube-v3/run-youtube-v3.sh"
grep -Fq -- '-c:v libx264' "$ROOT/youtube-v3/run-youtube-v3.sh"
grep -Fq -- '-c:a aac' "$ROOT/youtube-v3/run-youtube-v3.sh"
grep -Fq 'aresample=44100:async=1000:first_pts=0' "$ROOT/youtube-v3/run-youtube-v3.sh"
! grep -Eq '^Nice=|^CPUWeight=' "$ROOT/youtube-v3/fgbears-youtube-v3.service"

# General installation must include the independent Lovable cache as well as v3.
grep -Fq 'FGB_YOUTUBE_PACKET_ROUTER_ENABLE=0' "$ROOT/config/stream.env.example"
grep -Fq 'lovable-state-cache.py' "$ROOT/bin/install.sh"
grep -Fq 'fgbears-lovable-state-cache.service' "$ROOT/bin/install.sh"
grep -Eq '^systemctl enable .*fgbears-lovable-state-cache\.service .*fgbears-youtube-v3\.service' "$ROOT/bin/install.sh"
! grep -Fq 'systemctl enable fgbears-youtube-v2.service' "$ROOT/bin/install.sh"

# Health supervision is generation-aware and recovers only the desired destination.
grep -Fq 'YOUTUBE_V3_SERVICE=fgbears-youtube-v3.service' "$ROOT/bin/healthcheck.sh"
! grep -Fq 'YOUTUBE_SERVICE=${YOUTUBE_SERVICE:-' "$ROOT/bin/healthcheck.sh"
grep -Fq 'recover_youtube_destination' "$ROOT/bin/healthcheck.sh"
grep -Fq 'check_youtube_v3_pacing' "$ROOT/bin/healthcheck.sh"

test ! -d "$ROOT/youtube-v2"
test -d "$ROOT/quarantine/youtube-v2-retired-20260903"
if find "$ROOT/quarantine/youtube-v2-retired-20260903" -type f -perm /111 -print -quit | grep -q .; then echo 'v2 quarantine contains executable file' >&2; exit 1; fi
if find "$ROOT/quarantine/youtube-legacy" -type f -perm /111 -print -quit | grep -q .; then echo 'legacy quarantine contains executable file' >&2; exit 1; fi
if find "$ROOT" -type f -name 'stream.env' -print -quit | grep -q .; then echo 'A real stream.env file must never be committed.' >&2; exit 1; fi

# Smoke-test common ad/crawl renderers; the rebuild must not regress them.
cat > "$TMP/feed.json" <<'JSON'
{"kind":"house","sponsors":[{"businessName":"FGB","imageUrl":null,"promoMessage":"Bear Down","website":"https://epiccontentcreatorgrants.org/epic-media","durationSeconds":7}]}
JSON
cat > "$TMP/game.json" <<'JSON'
{"visible":false,"presentationMode":"crawl_only","adsEnabled":false}
JSON
SPONSOR_FEED_FILE="$TMP/feed.json" GAME_SCREEN_FEED_FILE="$TMP/game.json" CRAWL_RUNTIME_DIR="$TMP/runtime" AD_FRAME_FILE="$TMP/runtime/ad-frame.jpg" AD_OVERLAY_PORT=18787 python3 "$ROOT/bin/ad-overlay-smart.py" >"$TMP/ad.log" 2>&1 & OVERLAY_PID=$!
for _ in {1..40}; do curl -sf --max-time 1 http://127.0.0.1:18787/healthz >"$TMP/ad-health.json" && break; sleep 0.1; done
jq -e '.ok == true' "$TMP/ad-health.json" >/dev/null
curl -sf http://127.0.0.1:18787/frame.jpg -o "$TMP/ad-frame.jpg"
python3 - "$TMP/ad-frame.jpg" <<'PY'
from PIL import Image
import sys
im=Image.open(sys.argv[1]); im.load(); assert im.size==(1280,720)
PY
kill "$OVERLAY_PID"; wait "$OVERLAY_PID" 2>/dev/null || true; OVERLAY_PID=""

cat > "$TMP/crawl.json" <<'JSON'
{"active":true,"label":"FGB LIVE","message":"legacy first message","messages":[{"enabled":true,"text":"MESSAGE ONE"},{"enabled":true,"text":"MESSAGE TWO"},{"enabled":true,"text":"MESSAGE THREE"}],"separator":"•","speed":"normal","updatedAt":"2026-08-25T00:00:00Z"}
JSON
CRAWL_FEED_FILE="$TMP/crawl.json" CRAWL_RUNTIME_DIR="$TMP/runtime" CRAWL_OVERLAY_PORT=18788 CRAWL_OVERLAY_FPS=10 python3 "$ROOT/bin/crawl-overlay.py" >"$TMP/crawl.log" 2>&1 & CRAWL_PID=$!
for _ in {1..40}; do curl -sf --max-time 1 http://127.0.0.1:18788/healthz >"$TMP/crawl-health.json" && break; sleep 0.1; done
jq -e '.ok == true and .active == true and .messageCount == 3' "$TMP/crawl-health.json" >/dev/null
kill "$CRAWL_PID"; wait "$CRAWL_PID" 2>/dev/null || true; CRAWL_PID=""

mkdir -p "$TMP/media"
ffmpeg -hide_banner -loglevel error -f lavfi -i color=c=black:s=640x360:r=24:d=0.5 -f lavfi -i sine=frequency=440:sample_rate=44100:duration=0.5 -c:v libx264 -preset ultrafast -c:a aac -shortest "$TMP/source.mp4"
MEDIA_DIR="$TMP/media" bash "$ROOT/bin/normalize-library.sh" "$TMP/source.mp4" "$TMP/media/episode-01.mp4"
bash "$ROOT/bin/validate-media.sh" "$TMP/media"
install -m 0755 "$ROOT/bin/validate-media.sh" "$TMP/fgbears-validate"
VALIDATOR="$TMP/fgbears-validate" MEDIA_DIR="$TMP/media" PLAYLIST_FILE="$TMP/playlist.ffconcat" bash "$ROOT/bin/rebuild-playlist.sh"
grep -q 'episode-01.mp4' "$TMP/playlist.ffconcat"

echo 'FGBears Live integration tests passed: Lovable control plane + YouTube v3 architecture.'

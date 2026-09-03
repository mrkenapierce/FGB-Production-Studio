#!/usr/bin/env python3
"""Lovable-authoritative overlay worker for the existing YouTube v2 slot.

This worker changes only the 798x470 RGBA cover consumed by the already-running
YouTube v2 encoder. It never owns or modifies the master or Rumble streams.
The full locked QR creative is scaled as one asset. Missing, malformed, stale,
ad-break, or unreachable routing state always fails transparent.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from PIL import Image

WIDTH = 798
HEIGHT = 470
FPS = 10.0
POLL_SECONDS = 0.20
ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
STATE_FILE = Path(os.getenv("YOUTUBE_V2_STATE_FILE", "/run/fgbears-youtube-v2/overlay-state.json"))
CARD_BUILDER = Path(os.getenv(
    "YOUTUBE_REDIRECT_CARD_BUILDER",
    "/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py",
))
EXPECTED_REGION = {
    "x": 462, "y": 104, "width": WIDTH, "height": HEIGHT,
    "coordinateSpace": "pixels", "referenceWidth": 1280, "referenceHeight": 720,
}
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"


def fetch() -> dict:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "FGBears-YouTube-v2-Lovable/2.0",
    })
    with urllib.request.urlopen(req, timeout=1.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing payload is not an object")
    return payload


def validate(payload: dict) -> dict:
    trivia = payload.get("trivia")
    if not isinstance(trivia, dict):
        raise ValueError("missing trivia object")
    region = trivia.get("maskRegion")
    if not isinstance(region, dict):
        raise ValueError("missing maskRegion")
    for key, expected in EXPECTED_REGION.items():
        if region.get(key) != expected:
            raise ValueError(f"mask contract mismatch: {key}")

    creative = trivia.get("youtubeCreativeKey")
    presentation = trivia.get("presentation")
    if creative != EXPECTED_CREATIVE or not isinstance(presentation, dict):
        raise ValueError("unexpected creative or missing presentation")
    youtube = presentation.get("youtube")
    rumble = presentation.get("rumble")
    if not isinstance(youtube, dict) or not isinstance(rumble, dict):
        raise ValueError("missing platform presentation")
    if youtube.get("creativeKey") != creative or youtube.get("sourceTemplateKey") != creative:
        raise ValueError("YouTube creative mismatch")
    if youtube.get("presentationMode") != "full_creative_scaled":
        raise ValueError("invalid YouTube presentation mode")
    if youtube.get("rendersRealQuestion") is not False or rumble.get("rendersRealQuestion") is not True:
        raise ValueError("platform question visibility contract mismatch")
    masked = youtube.get("maskedRegion")
    if not isinstance(masked, dict):
        raise ValueError("missing YouTube maskedRegion")
    for key in ("x", "y", "width", "height"):
        if masked.get(key) != EXPECTED_REGION[key]:
            raise ValueError("YouTube maskedRegion mismatch")
    return trivia


def should_cover(trivia: dict) -> bool:
    return (
        trivia.get("youtubeMaskActive") is True
        and str(trivia.get("phase") or "").strip().lower() == "question"
        and trivia.get("stale") is not True
        and trivia.get("adsVisible") is not True
        and trivia.get("isAdBreak") is not True
        and trivia.get("adBreakActive") is not True
    )


def load_builder():
    if not CARD_BUILDER.is_file():
        raise FileNotFoundError(f"locked card builder missing: {CARD_BUILDER}")
    spec = importlib.util.spec_from_file_location("fgb_locked_youtube_card", CARD_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load locked card builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise RuntimeError("locked card builder has no build()")
    return module


def build_active_frame() -> bytes:
    source = load_builder().build().convert("RGBA")
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (WIDTH, HEIGHT), (11, 22, 42, 255))
    out.paste(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2), source)
    return out.tobytes()


def write_state(*, ok: bool, phase: str, active: bool, last_good: float, error: str | None = None) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "ok": ok,
            "phase": phase,
            "active": active,
            "lastGoodEpoch": last_good,
            "lastGoodAgeSeconds": max(0.0, time.time() - last_good) if last_good else None,
            "maskRegion": EXPECTED_REGION,
            "frameSize": [WIDTH, HEIGHT],
            "creativeKey": EXPECTED_CREATIVE,
            "presentationMode": "full_creative_scaled",
            "routingAuthority": "lovable_public_stream_routing",
            "fps": FPS,
            "error": error,
        }
        fd, name = tempfile.mkstemp(prefix="overlay-state-", suffix=".json", dir=str(STATE_FILE.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(name, STATE_FILE)
    except Exception as exc:
        print(f"state write warning: {exc}", file=sys.stderr)


def self_test() -> int:
    active = build_active_frame()
    assert len(active) == WIDTH * HEIGHT * 4
    assert min(active[3::4]) == 255 and max(active[3::4]) == 255
    trivia = validate(fetch())
    print(json.dumps({
        "ok": True,
        "activeNow": should_cover(trivia),
        "maskRegion": EXPECTED_REGION,
        "frameSize": [WIDTH, HEIGHT],
        "creativeKey": EXPECTED_CREATIVE,
    }, separators=(",", ":")))
    return 0


def stream() -> int:
    active_frame = build_active_frame()
    transparent = bytes(WIDTH * HEIGHT * 4)
    active = False
    phase = "unknown"
    last_good = 0.0
    last_poll = 0.0
    deadline = time.monotonic()
    interval = 1.0 / FPS

    while True:
        now = time.monotonic()
        if now - last_poll >= POLL_SECONDS:
            try:
                trivia = validate(fetch())
                phase = str(trivia.get("phase") or "")
                active = should_cover(trivia)
                last_good = time.time()
                write_state(ok=True, phase=phase, active=active, last_good=last_good)
            except Exception as exc:
                active = False
                write_state(ok=False, phase=phase, active=False, last_good=last_good, error=str(exc))
                print(f"routing poll warning: {exc}", file=sys.stderr)
            last_poll = now

        try:
            sys.stdout.buffer.write(active_frame if active else transparent)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            return 0

        deadline += interval
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -interval:
            deadline = time.monotonic()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else stream()


if __name__ == "__main__":
    raise SystemExit(main())

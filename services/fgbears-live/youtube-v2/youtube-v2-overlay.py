#!/usr/bin/env python3
"""Local-state-only difference-layer renderer for the existing YouTube v2 slot.

No network I/O is permitted here. The independent Lovable state-cache service
owns HTTP. This process reads only its atomic local cache, pre-renders the
approved static creative once, and emits either that frame or transparent RGBA.
Any missing, malformed, expired, ambiguous, ad-break, or unknown-creative state
fails transparent. It never owns or modifies the master or Rumble streams.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from PIL import Image

WIDTH = 798
HEIGHT = 470
FPS = 10.0
CACHE_FILE = Path(os.getenv(
    "FGB_CONTROL_STATE_FILE", "/run/fgbears-control-plane/stream-state.json"
))
CARD_BUILDER = Path(os.getenv(
    "YOUTUBE_REDIRECT_CARD_BUILDER",
    "/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py",
))
EXPECTED_SCHEMA = "fgb-stream-state/v1"
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"
EXPECTED_REGION = {
    "x": 462, "y": 104, "width": WIDTH, "height": HEIGHT,
    "coordinateSpace": "pixels", "referenceWidth": 1280, "referenceHeight": 720,
}


def parse_time(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.timestamp()


def load_local() -> dict:
    with CACHE_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("local state is not an object")
    return payload


def validate_local(payload: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if payload.get("schemaVersion") != EXPECTED_SCHEMA:
        raise ValueError("unsupported schemaVersion")
    if parse_time(payload.get("validUntil")) <= now:
        raise ValueError("local state expired")
    p = payload.get("presentation")
    if not isinstance(p, dict):
        raise ValueError("missing presentation")
    ad_break = p.get("adBreak")
    trivia = p.get("trivia")
    routing = p.get("routing")
    overlay = p.get("overlay")
    if not all(isinstance(x, dict) for x in (ad_break, trivia, routing, overlay)):
        raise ValueError("incomplete presentation")
    rumble = routing.get("rumble")
    youtube = routing.get("youtube")
    if not isinstance(rumble, dict) or not isinstance(youtube, dict):
        raise ValueError("missing destination routing")
    if rumble.get("rendersRealQuestion") is not True:
        raise ValueError("Rumble invariant mismatch")
    difference = youtube.get("differenceLayer")
    if not isinstance(difference, dict) or type(difference.get("enabled")) is not bool:
        raise ValueError("missing differenceLayer decision")
    region = difference.get("region") or overlay.get("maskRegion")
    if not isinstance(region, dict):
        raise ValueError("missing difference-layer region")
    for key, expected in EXPECTED_REGION.items():
        if region.get(key) != expected:
            raise ValueError(f"mask contract mismatch: {key}")
    return p


def should_cover(presentation: dict) -> bool:
    try:
        ad_break = presentation["adBreak"]
        trivia = presentation["trivia"]
        difference = presentation["routing"]["youtube"]["differenceLayer"]
        return (
            difference.get("enabled") is True
            and difference.get("creativeKey") == EXPECTED_CREATIVE
            and ad_break.get("active") is False
            and str(trivia.get("phase") or "").strip().lower() == "question"
            and trivia.get("stale") is not True
            and trivia.get("fresh") is not False
            and trivia.get("gameVisible") is True
            and trivia.get("youtubeRedirectRequired") is True
        )
    except (KeyError, TypeError):
        return False


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
    # Static creative is rasterized exactly once per renderer process.
    source = load_builder().build().convert("RGBA")
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (WIDTH, HEIGHT), (11, 22, 42, 255))
    out.paste(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2), source)
    return out.tobytes()


def read_decision() -> bool:
    try:
        return should_cover(validate_local(load_local()))
    except Exception as exc:
        print(f"local control-state warning: {exc}", file=sys.stderr)
        return False


def self_test() -> int:
    active = build_active_frame()
    assert len(active) == WIDTH * HEIGHT * 4
    assert min(active[3::4]) == 255 and max(active[3::4]) == 255
    print(json.dumps({
        "ok": True,
        "activeNow": read_decision(),
        "maskRegion": EXPECTED_REGION,
        "frameSize": [WIDTH, HEIGHT],
        "creativeKey": EXPECTED_CREATIVE,
        "networkInRenderer": False,
    }, separators=(",", ":")))
    return 0


def stream() -> int:
    active_frame = build_active_frame()
    transparent = bytes(WIDTH * HEIGHT * 4)
    active = False
    last_mtime_ns: int | None = None
    deadline = time.monotonic()
    interval = 1.0 / FPS

    while True:
        # Local filesystem only. Re-parse state only when the atomic cache file
        # changes; expiration is still checked every frame below.
        try:
            stat = CACHE_FILE.stat()
            if stat.st_mtime_ns != last_mtime_ns:
                active = read_decision()
                last_mtime_ns = stat.st_mtime_ns
            elif active:
                # A formerly active LKG must turn transparent when validUntil
                # expires even if the cache daemon has stopped updating it.
                active = read_decision()
        except OSError:
            active = False
            last_mtime_ns = None

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

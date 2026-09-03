#!/usr/bin/env python3
"""FGBears YouTube v3 destination-only difference-layer renderer.

Hard boundary: this renderer performs NO network I/O. Lovable is polled by the
independent lovable-state-cache.py process, which atomically publishes validated
state locally. A validated positive concealment trigger is latched for at least
15 seconds so a short phase transition cannot expose the question prematurely.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from PIL import Image

REFERENCE_WIDTH = 1280
REFERENCE_HEIGHT = 720
SOURCE_X = 462
SOURCE_Y = 104
SOURCE_WIDTH = 798
SOURCE_HEIGHT = 470
OUTPUT_WIDTH = 640
OUTPUT_HEIGHT = 360
OUTPUT_X = math.floor(SOURCE_X * OUTPUT_WIDTH / REFERENCE_WIDTH)
OUTPUT_Y = math.floor(SOURCE_Y * OUTPUT_HEIGHT / REFERENCE_HEIGHT)
OUTPUT_RIGHT = math.ceil((SOURCE_X + SOURCE_WIDTH) * OUTPUT_WIDTH / REFERENCE_WIDTH)
OUTPUT_BOTTOM = math.ceil((SOURCE_Y + SOURCE_HEIGHT) * OUTPUT_HEIGHT / REFERENCE_HEIGHT)
WIDTH = OUTPUT_RIGHT - OUTPUT_X
HEIGHT = OUTPUT_BOTTOM - OUTPUT_Y
FPS = 5.0
HOLD_SECONDS = float(os.getenv("YOUTUBE_V3_CONCEALMENT_HOLD_SECONDS", "15"))
if HOLD_SECONDS <= 0:
    raise ValueError("YOUTUBE_V3_CONCEALMENT_HOLD_SECONDS must be positive")
STATE_FILE = Path(os.getenv(
    "FGB_CONTROL_STATE_FILE", "/run/fgbears-control-plane/stream-state.json"
))
CREATIVE_DIR = Path(os.getenv(
    "YOUTUBE_V3_CREATIVE_DIR", "/opt/fgbears-live/youtube-v3/creatives"
))
BUILTIN_REDIRECT_KEY = "yt_rumble_trivia_redirect"
EXPECTED_SCHEMA = "fgb-stream-state/v1"
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
EXPECTED_REGION = {
    "x": SOURCE_X,
    "y": SOURCE_Y,
    "width": SOURCE_WIDTH,
    "height": SOURCE_HEIGHT,
    "coordinateSpace": "pixels",
    "referenceWidth": REFERENCE_WIDTH,
    "referenceHeight": REFERENCE_HEIGHT,
}
OUTPUT_REGION = {
    "x": OUTPUT_X,
    "y": OUTPUT_Y,
    "width": WIDTH,
    "height": HEIGHT,
    "referenceWidth": OUTPUT_WIDTH,
    "referenceHeight": OUTPUT_HEIGHT,
}
TRANSPARENT = bytes(WIDTH * HEIGHT * 4)
_FRAME_CACHE: dict[str, bytes] = {}


class ConcealmentLatch:
    """Minimum-duration latch driven only by validated positive triggers."""

    def __init__(self, hold_seconds: float = HOLD_SECONDS) -> None:
        self.hold_seconds = hold_seconds
        self.hold_until = 0.0
        self.was_triggered = False

    def update(self, triggered: bool, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if triggered and not self.was_triggered:
            self.hold_until = max(self.hold_until, now + self.hold_seconds)
        self.was_triggered = triggered
        return triggered or now < self.hold_until


def parse_timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return dt.timestamp()


def normalize_key(value: object) -> str:
    key = str(value or "").strip()
    if not KEY_RE.fullmatch(key):
        raise ValueError("invalid or missing YouTube creative key")
    return key


def available_creative_keys() -> list[str]:
    keys: set[str] = set()
    try:
        for path in CREATIVE_DIR.glob("*.png"):
            if KEY_RE.fullmatch(path.stem):
                keys.add(path.stem)
    except OSError:
        pass
    return sorted(keys)


def load_local_state() -> dict:
    with STATE_FILE.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("local control state is not an object")
    return payload


def validate(payload: dict, *, now: float | None = None) -> tuple[dict, str]:
    now = time.time() if now is None else now
    if payload.get("schemaVersion") != EXPECTED_SCHEMA:
        raise ValueError("unsupported schemaVersion")
    if parse_timestamp(payload.get("validUntil")) <= now:
        raise ValueError("local control state expired")
    revision = payload.get("revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("missing revision")

    presentation = payload.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("missing presentation")
    ad_break = presentation.get("adBreak")
    trivia = presentation.get("trivia")
    routing = presentation.get("routing")
    if not isinstance(ad_break, dict) or not isinstance(trivia, dict) or not isinstance(routing, dict):
        raise ValueError("incomplete presentation")
    rumble = routing.get("rumble")
    youtube = routing.get("youtube")
    if not isinstance(rumble, dict) or not isinstance(youtube, dict):
        raise ValueError("missing destination routing")
    if rumble.get("rendersRealQuestion") is not True:
        raise ValueError("Rumble real-question invariant violated")
    difference = youtube.get("differenceLayer")
    if not isinstance(difference, dict) or type(difference.get("enabled")) is not bool:
        raise ValueError("missing YouTube differenceLayer decision")

    region = difference.get("region") or (presentation.get("mask") or {}).get("region")
    if not isinstance(region, dict):
        raise ValueError("missing mask region")
    for key, expected in EXPECTED_REGION.items():
        if region.get(key) != expected:
            raise ValueError(f"mask contract mismatch: {key}")

    key = normalize_key(difference.get("creativeKey") or BUILTIN_REDIRECT_KEY)
    return presentation, key


def should_cover(presentation: dict, key: str) -> bool:
    try:
        trivia = presentation["trivia"]
        difference = presentation["routing"]["youtube"]["differenceLayer"]
        return (
            difference.get("enabled") is True
            and key == BUILTIN_REDIRECT_KEY
            and difference.get("creativeKey") == BUILTIN_REDIRECT_KEY
            and trivia.get("questionVisible") is True
            and trivia.get("youtubeRedirectRequired") is True
        )
    except (KeyError, TypeError):
        return False


def build_frame(key: str) -> bytes:
    cached = _FRAME_CACHE.get(key)
    if cached is not None:
        return cached
    if key != BUILTIN_REDIRECT_KEY:
        raise ValueError(f"creative is not approved: {key}")
    path = CREATIVE_DIR / f"{key}.png"
    if not path.is_file():
        raise FileNotFoundError(f"creative is not installed: {key}")
    source = Image.open(path).convert("RGBA")
    if source.size != (WIDTH, HEIGHT):
        source = source.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    frame = source.tobytes()
    if len(frame) != WIDTH * HEIGHT * 4:
        raise RuntimeError("creative frame has invalid byte size")
    _FRAME_CACHE[key] = frame
    return frame


def local_decision() -> tuple[bool, str | None, str | None]:
    try:
        presentation, key = validate(load_local_state())
        if key not in available_creative_keys():
            raise ValueError(f"creative is not installed: {key}")
        return should_cover(presentation, key), key, None
    except Exception as exc:
        return False, None, str(exc)


def write_all(frame: bytes) -> None:
    fd = sys.stdout.fileno()
    view = memoryview(frame)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def self_test() -> int:
    keys = available_creative_keys()
    if BUILTIN_REDIRECT_KEY not in keys:
        raise RuntimeError("built-in redirect creative missing from local allowlist")
    frame = build_frame(BUILTIN_REDIRECT_KEY)
    assert len(frame) == WIDTH * HEIGHT * 4
    latch = ConcealmentLatch(15.0)
    assert latch.update(True, now=100.0) is True
    assert latch.update(False, now=114.999) is True
    assert latch.update(False, now=115.001) is False
    assert latch.update(True, now=120.0) is True
    assert latch.update(False, now=134.999) is True
    assert latch.update(False, now=135.001) is False
    active, key, error = local_decision()
    print(json.dumps({
        "ok": True,
        "activeNow": active,
        "requestedCreativeKey": key,
        "localStateError": error,
        "availableCreativeKeys": keys,
        "fps": FPS,
        "holdSeconds": HOLD_SECONDS,
        "sourceMaskRegion": EXPECTED_REGION,
        "outputMaskRegion": OUTPUT_REGION,
        "networkInRenderer": False,
    }, separators=(",", ":")))
    return 0


def stream() -> int:
    active_frame = build_frame(BUILTIN_REDIRECT_KEY)
    interval = 1.0 / FPS
    deadline = time.monotonic()
    last_mtime_ns: int | None = None
    raw_active = False
    latch = ConcealmentLatch()

    while True:
        try:
            mtime_ns = STATE_FILE.stat().st_mtime_ns
            if mtime_ns != last_mtime_ns or raw_active:
                raw_active, _, error = local_decision()
                if error:
                    print(f"local control-state warning: {error}", file=sys.stderr)
                last_mtime_ns = mtime_ns
        except OSError as exc:
            raw_active = False
            last_mtime_ns = None
            print(f"local control-state warning: {exc}", file=sys.stderr)

        active = latch.update(raw_active)
        try:
            write_all(active_frame if active else TRANSPARENT)
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

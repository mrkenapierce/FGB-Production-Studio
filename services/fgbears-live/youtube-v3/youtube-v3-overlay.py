#!/usr/bin/env python3
"""FGBears YouTube v3 destination-only difference-layer renderer.

Hard boundary: this renderer performs NO network I/O. Lovable is polled by the
independent lovable-state-cache.py process, which atomically publishes validated
state locally. This media-clock process reads only that local cache and fails
transparent for missing, malformed, expired, ambiguous, ad-break, or unknown-
creative state.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time

from PIL import Image

WIDTH = 798
HEIGHT = 470
FPS = 5.0
STATE_FILE = Path(os.getenv(
    "FGB_CONTROL_STATE_FILE", "/run/fgbears-control-plane/stream-state.json"
))
CREATIVE_DIR = Path(os.getenv(
    "YOUTUBE_V3_CREATIVE_DIR", "/opt/fgbears-live/youtube-v3/creatives"
))
BUILTIN_REDIRECT_KEY = "yt_rumble_trivia_redirect"
EXPECTED_SCHEMA = "fgb-stream-state/v1"
VISIBLE_QUESTION_PHASES = {"question", "revealed"}
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
EXPECTED_REGION = {
    "x": 462,
    "y": 104,
    "width": WIDTH,
    "height": HEIGHT,
    "coordinateSpace": "pixels",
    "referenceWidth": 1280,
    "referenceHeight": 720,
}
TRANSPARENT = bytes(WIDTH * HEIGHT * 4)
_FRAME_CACHE: dict[str, bytes] = {}


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
        ad_break = presentation["adBreak"]
        trivia = presentation["trivia"]
        difference = presentation["routing"]["youtube"]["differenceLayer"]
        phase = str(trivia.get("phase") or "").strip().lower()
        return (
            difference.get("enabled") is True
            and key == BUILTIN_REDIRECT_KEY
            and difference.get("creativeKey") == BUILTIN_REDIRECT_KEY
            and ad_break.get("active") is False
            and phase in VISIBLE_QUESTION_PHASES
            and trivia.get("questionVisible") is True
            and trivia.get("stale") is not True
            and trivia.get("gameVisible") is True
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
        source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        out = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        out.alpha_composite(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2))
        source = out
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
    active, key, error = local_decision()
    print(json.dumps({
        "ok": True,
        "activeNow": active,
        "requestedCreativeKey": key,
        "localStateError": error,
        "availableCreativeKeys": keys,
        "fps": FPS,
        "maskRegion": EXPECTED_REGION,
        "networkInRenderer": False,
    }, separators=(",", ":")))
    return 0


def stream() -> int:
    # Static approved creative is rasterized once and retained in memory.
    active_frame = build_frame(BUILTIN_REDIRECT_KEY)
    interval = 1.0 / FPS
    deadline = time.monotonic()
    last_mtime_ns: int | None = None
    active = False

    while True:
        # Local filesystem only. Re-read on atomic-cache changes; while active,
        # re-check every media tick so validUntil expiration cannot leave a
        # stuck cover if the cache daemon stops.
        try:
            mtime_ns = STATE_FILE.stat().st_mtime_ns
            if mtime_ns != last_mtime_ns or active:
                active, _, error = local_decision()
                if error:
                    print(f"local control-state warning: {error}", file=sys.stderr)
                last_mtime_ns = mtime_ns
        except OSError as exc:
            active = False
            last_mtime_ns = None
            print(f"local control-state warning: {exc}", file=sys.stderr)

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

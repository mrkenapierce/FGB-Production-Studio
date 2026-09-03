#!/usr/bin/env python3
"""FGBears YouTube v3 destination-only overlay worker.

Media and control clocks are deliberately independent. The main thread emits a
fixed local RGBA frame clock. A background control thread polls Lovable and only
updates cached presentation state. Slow or failed routing requests therefore
cannot stall the media pipe.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from PIL import Image

WIDTH = 798
HEIGHT = 470
FPS = 5.0
POLL_SECONDS = 0.25
ROUTING_TIMEOUT_SECONDS = 1.5
ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
STATE_FILE = Path(os.getenv("YOUTUBE_V3_STATE_FILE", "/run/fgbears-youtube-v3/overlay-state.json"))
CREATIVE_DIR = Path(os.getenv("YOUTUBE_V3_CREATIVE_DIR", "/opt/fgbears-live/youtube-v3/creatives"))
BUILTIN_REDIRECT_KEY = "yt_rumble_trivia_redirect"
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


def fetch() -> tuple[dict, float]:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-YouTube-v3-Control/1.0",
        },
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=ROUTING_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    latency = time.monotonic() - started
    if not isinstance(payload, dict):
        raise ValueError("routing payload is not an object")
    return payload, latency


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

    creative = normalize_key(trivia.get("youtubeCreativeKey"))
    presentation = trivia.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("missing presentation")
    youtube = presentation.get("youtube")
    rumble = presentation.get("rumble")
    if not isinstance(youtube, dict) or not isinstance(rumble, dict):
        raise ValueError("missing platform presentation")
    if youtube.get("creativeKey") != creative or youtube.get("sourceTemplateKey") != creative:
        raise ValueError("YouTube creative contract mismatch")
    if youtube.get("presentationMode") != "full_creative_scaled":
        raise ValueError("invalid YouTube presentation mode")
    if youtube.get("rendersRealQuestion") is not False:
        raise ValueError("YouTube question visibility contract mismatch")
    if rumble.get("rendersRealQuestion") is not True:
        raise ValueError("Rumble must remain the canonical live-question presentation")
    masked = youtube.get("maskedRegion")
    if not isinstance(masked, dict):
        raise ValueError("missing YouTube maskedRegion")
    for key in ("x", "y", "width", "height"):
        if masked.get(key) != EXPECTED_REGION[key]:
            raise ValueError("YouTube maskedRegion mismatch")
    trivia["_validatedCreativeKey"] = creative
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


def build_frame(key: str) -> bytes:
    cached = _FRAME_CACHE.get(key)
    if cached is not None:
        return cached
    path = CREATIVE_DIR / f"{key}.png"
    if not path.is_file():
        raise FileNotFoundError(f"creative is not approved/installed: {key}")
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


class SharedState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.frame = TRANSPARENT
        self.ok = False
        self.phase = "unknown"
        self.active = False
        self.requested_key: str | None = None
        self.rendered_key: str | None = None
        self.last_good = 0.0
        self.error: str | None = "routing not loaded"
        self.routing_latency = 0.0
        self.frame_clock_misses = 0

    def publish_success(self, trivia: dict, latency: float) -> None:
        key = trivia["_validatedCreativeKey"]
        active = should_cover(trivia)
        frame = build_frame(key) if active else TRANSPARENT
        with self.lock:
            self.frame = frame
            self.ok = True
            self.phase = str(trivia.get("phase") or "")
            self.active = active
            self.requested_key = key
            self.rendered_key = key if active else None
            self.last_good = time.time()
            self.error = None
            self.routing_latency = latency

    def publish_failure(self, exc: Exception) -> None:
        with self.lock:
            self.frame = TRANSPARENT
            self.ok = False
            self.active = False
            self.rendered_key = None
            self.error = str(exc)

    def mark_clock_miss(self) -> None:
        with self.lock:
            self.frame_clock_misses += 1

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "frame": self.frame,
                "ok": self.ok,
                "phase": self.phase,
                "active": self.active,
                "creativeKey": self.requested_key,
                "renderedCreativeKey": self.rendered_key,
                "lastGoodEpoch": self.last_good,
                "error": self.error,
                "routingLatencyMs": round(self.routing_latency * 1000.0, 2),
                "frameClockMisses": self.frame_clock_misses,
            }


STATE = SharedState()


def write_state(snapshot: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "workerVersion": "youtube-v3",
            "ok": snapshot["ok"],
            "phase": snapshot["phase"],
            "active": snapshot["active"],
            "lastGoodEpoch": snapshot["lastGoodEpoch"],
            "lastGoodAgeSeconds": max(0.0, time.time() - snapshot["lastGoodEpoch"]) if snapshot["lastGoodEpoch"] else None,
            "maskRegion": EXPECTED_REGION,
            "frameSize": [WIDTH, HEIGHT],
            "creativeKey": snapshot["creativeKey"],
            "renderedCreativeKey": snapshot["renderedCreativeKey"],
            "availableCreativeKeys": available_creative_keys(),
            "presentationMode": "full_creative_scaled",
            "routingAuthority": "lovable_public_stream_routing",
            "fps": FPS,
            "pollSeconds": POLL_SECONDS,
            "routingLatencyMs": snapshot["routingLatencyMs"],
            "frameClockMisses": snapshot["frameClockMisses"],
            "error": snapshot["error"],
        }
        fd, name = tempfile.mkstemp(prefix="overlay-state-", suffix=".json", dir=str(STATE_FILE.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(name, STATE_FILE)
    except Exception as exc:
        print(f"state write warning: {exc}", file=sys.stderr)


def control_loop() -> None:
    deadline = time.monotonic()
    while True:
        try:
            payload, latency = fetch()
            STATE.publish_success(validate(payload), latency)
        except Exception as exc:
            STATE.publish_failure(exc)
            print(f"routing/creative warning: {exc}", file=sys.stderr)
        write_state(STATE.snapshot())
        deadline += POLL_SECONDS
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            deadline = time.monotonic()


def write_all(frame: bytes) -> None:
    fd = sys.stdout.fileno()
    view = memoryview(frame)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def self_test(check_routing: bool = True) -> int:
    keys = available_creative_keys()
    if BUILTIN_REDIRECT_KEY not in keys:
        raise RuntimeError("built-in redirect creative missing from local allowlist")
    for key in keys:
        assert len(build_frame(key)) == WIDTH * HEIGHT * 4
    result = {"ok": True, "availableCreativeKeys": keys, "fps": FPS, "maskRegion": EXPECTED_REGION}
    if check_routing:
        payload, latency = fetch()
        trivia = validate(payload)
        key = trivia["_validatedCreativeKey"]
        if should_cover(trivia):
            build_frame(key)
        result.update({"activeNow": should_cover(trivia), "requestedCreativeKey": key, "routingLatencyMs": round(latency * 1000, 2)})
    print(json.dumps(result, separators=(",", ":")))
    return 0


def stream() -> int:
    threading.Thread(target=control_loop, name="lovable-control", daemon=True).start()
    interval = 1.0 / FPS
    deadline = time.monotonic()
    while True:
        snapshot = STATE.snapshot()
        try:
            write_all(snapshot["frame"])
        except BrokenPipeError:
            return 0
        deadline += interval
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -interval:
            STATE.mark_clock_miss()
            deadline = time.monotonic()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test(check_routing=not args.offline)
    return stream()


if __name__ == "__main__":
    raise SystemExit(main())

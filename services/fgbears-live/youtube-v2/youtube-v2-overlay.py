#!/usr/bin/env python3
"""Lovable-authoritative destination overlay for the sole YouTube v2 output.

The shared FGB program and Rumble relay are never modified here. Lovable only
selects a destination-specific creative key. This worker renders that key from
an approved local asset and emits a fixed 798x470 RGBA stream to the existing
YouTube v2 FFmpeg compositor.

Safety:
- no browser source or remote creative URL is accepted;
- unknown/missing/stale/malformed state fails transparent;
- only the current question phase may activate the mask;
- ad breaks always fail transparent;
- the mask geometry is fixed to the production game/ad panel.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
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
STATE_FILE = Path(
    os.getenv("YOUTUBE_V2_STATE_FILE", "/run/fgbears-youtube-v2/overlay-state.json")
)
CREATIVE_DIR = Path(
    os.getenv("YOUTUBE_V2_CREATIVE_DIR", "/opt/fgbears-live/youtube-v2/creatives")
)
REDIRECT_BUILDER = Path(
    os.getenv(
        "YOUTUBE_REDIRECT_CARD_BUILDER",
        "/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py",
    )
)
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
_FRAME_CACHE: dict[str, bytes] = {}


def fetch() -> dict:
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
            "User-Agent": "FGBears-YouTube-v2-Lovable/3.0",
        },
    )
    with urllib.request.urlopen(req, timeout=1.5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing payload is not an object")
    return payload


def normalize_key(value: object) -> str:
    key = str(value or "").strip()
    if not KEY_RE.fullmatch(key):
        raise ValueError("invalid or missing YouTube creative key")
    return key


def available_creative_keys() -> list[str]:
    keys = {BUILTIN_REDIRECT_KEY}
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


def load_builder():
    if not REDIRECT_BUILDER.is_file():
        raise FileNotFoundError(f"locked redirect builder missing: {REDIRECT_BUILDER}")
    spec = importlib.util.spec_from_file_location("fgb_locked_youtube_card", REDIRECT_BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load locked redirect builder")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise RuntimeError("locked redirect builder has no build()")
    return module


def source_image_for(key: str) -> tuple[Image.Image, bool]:
    """Return source image and whether the legacy locked background is required."""
    if key == BUILTIN_REDIRECT_KEY:
        return load_builder().build().convert("RGBA"), True
    path = CREATIVE_DIR / f"{key}.png"
    if not path.is_file():
        raise FileNotFoundError(f"creative is not approved/installed: {key}")
    return Image.open(path).convert("RGBA"), False


def build_frame(key: str) -> bytes:
    cached = _FRAME_CACHE.get(key)
    if cached is not None:
        return cached

    source, locked_background = source_image_for(key)
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    background = (11, 22, 42, 255) if locked_background else (0, 0, 0, 0)
    out = Image.new("RGBA", (WIDTH, HEIGHT), background)
    x = (WIDTH - source.width) // 2
    y = (HEIGHT - source.height) // 2
    out.alpha_composite(source, (x, y))
    frame = out.tobytes()
    if len(frame) != WIDTH * HEIGHT * 4:
        raise RuntimeError("creative frame has invalid byte size")
    _FRAME_CACHE[key] = frame
    return frame


def write_state(
    *,
    ok: bool,
    phase: str,
    active: bool,
    requested_key: str | None,
    rendered_key: str | None,
    last_good: float,
    error: str | None = None,
) -> None:
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
            "creativeKey": requested_key,
            "renderedCreativeKey": rendered_key,
            "availableCreativeKeys": available_creative_keys(),
            "presentationMode": "full_creative_scaled",
            "routingAuthority": "lovable_public_stream_routing",
            "fps": FPS,
            "error": error,
        }
        fd, name = tempfile.mkstemp(
            prefix="overlay-state-", suffix=".json", dir=str(STATE_FILE.parent)
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(name, STATE_FILE)
    except Exception as exc:
        print(f"state write warning: {exc}", file=sys.stderr)


def self_test() -> int:
    keys = available_creative_keys()
    if BUILTIN_REDIRECT_KEY not in keys:
        raise RuntimeError("built-in redirect creative missing from allowlist")
    for key in keys:
        frame = build_frame(key)
        assert len(frame) == WIDTH * HEIGHT * 4

    trivia = validate(fetch())
    key = trivia["_validatedCreativeKey"]
    active = should_cover(trivia)
    if active:
        build_frame(key)

    print(
        json.dumps(
            {
                "ok": True,
                "activeNow": active,
                "requestedCreativeKey": key,
                "availableCreativeKeys": keys,
                "maskRegion": EXPECTED_REGION,
                "frameSize": [WIDTH, HEIGHT],
            },
            separators=(",", ":"),
        )
    )
    return 0


def stream() -> int:
    transparent = bytes(WIDTH * HEIGHT * 4)
    frame = transparent
    active = False
    phase = "unknown"
    requested_key: str | None = None
    rendered_key: str | None = None
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
                requested_key = trivia["_validatedCreativeKey"]
                if should_cover(trivia):
                    frame = build_frame(requested_key)
                    active = True
                    rendered_key = requested_key
                else:
                    frame = transparent
                    active = False
                    rendered_key = None
                last_good = time.time()
                write_state(
                    ok=True,
                    phase=phase,
                    active=active,
                    requested_key=requested_key,
                    rendered_key=rendered_key,
                    last_good=last_good,
                )
            except Exception as exc:
                frame = transparent
                active = False
                rendered_key = None
                write_state(
                    ok=False,
                    phase=phase,
                    active=False,
                    requested_key=requested_key,
                    rendered_key=None,
                    last_good=last_good,
                    error=str(exc),
                )
                print(f"routing/creative warning: {exc}", file=sys.stderr)
            last_poll = now

        try:
            sys.stdout.buffer.write(frame)
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

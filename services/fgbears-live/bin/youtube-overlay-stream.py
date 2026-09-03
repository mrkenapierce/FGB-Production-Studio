#!/usr/bin/env python3
"""Minimal YouTube-only trivia concealment raw-RGBA producer.

Writes one 798x470 RGBA frame to stdout at 10 fps. The frame is transparent
unless Lovable says a trivia question is active (or the clean transition into
one is underway), in which case it is the locked Rumble redirect creative.
There is no HTTP server, routing daemon, cache service, or separate watchdog.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
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
CARD_BUILDER = Path(
    os.getenv(
        "YOUTUBE_REDIRECT_CARD_BUILDER",
        "/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py",
    )
)
EXPECTED_REGION = {
    "x": 462,
    "y": 104,
    "width": WIDTH,
    "height": HEIGHT,
    "coordinateSpace": "pixels",
    "referenceWidth": 1280,
    "referenceHeight": 720,
}
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"


def fetch() -> dict:
    p = urllib.parse.urlsplit(ROUTING_URL)
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    q.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), p.fragment))
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-Minimal-YouTube-Overlay/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=1.5) as r:
        value = json.loads(r.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("routing payload is not an object")
    return value


def validate(payload: dict) -> dict:
    trivia = payload.get("trivia")
    if not isinstance(trivia, dict):
        raise ValueError("missing trivia object")
    region = trivia.get("maskRegion")
    if not isinstance(region, dict):
        raise ValueError("missing mask region")
    for key, value in EXPECTED_REGION.items():
        if region.get(key) != value:
            raise ValueError(f"unexpected mask region {key}={region.get(key)!r}")
    if trivia.get("youtubeCreativeKey") != EXPECTED_CREATIVE:
        raise ValueError("unexpected YouTube creative")
    return trivia


def should_cover(trivia: dict) -> bool:
    phase = str(trivia.get("phase") or "")
    question = trivia.get("questionActive") is True
    mask = trivia.get("youtubeMaskActive") is True
    session = trivia.get("active") is True
    ads = trivia.get("adsVisible") is True
    ad_break = trivia.get("isAdBreak") is True or trivia.get("adBreakActive") is True
    prearm = session and phase == "transition" and not ads and not ad_break
    return phase == "question" or question or mask or prearm


def build_active() -> bytes:
    if not CARD_BUILDER.is_file():
        raise FileNotFoundError(CARD_BUILDER)
    with tempfile.TemporaryDirectory(prefix="fgb-yt-overlay-") as tmp:
        png = Path(tmp) / "card.png"
        subprocess.run(
            [sys.executable, str(CARD_BUILDER), str(png)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        with Image.open(png) as im:
            source = im.convert("RGBA")
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (WIDTH, HEIGHT), (11, 22, 42, 255))
    out.paste(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2), source)
    return out.tobytes()


def main() -> None:
    active_frame = build_active()
    transparent = bytes(WIDTH * HEIGHT * 4)
    active = False
    last_poll = 0.0
    deadline = time.monotonic()
    interval = 1.0 / FPS

    # Obtain one valid contract before emitting frames. This prevents accidental
    # concealment at the wrong coordinates after an upstream schema change.
    for attempt in range(30):
        try:
            active = should_cover(validate(fetch()))
            break
        except Exception as exc:
            if attempt == 29:
                raise
            print(f"routing startup retry: {exc}", file=sys.stderr)
            time.sleep(1)

    while True:
        now = time.monotonic()
        if now - last_poll >= POLL_SECONDS:
            try:
                active = should_cover(validate(fetch()))
            except Exception as exc:
                # Fail closed only if already concealed. Never drop a cover due
                # to a control-plane timeout in the middle of a question.
                print(f"routing poll warning: {exc}", file=sys.stderr)
            last_poll = now

        try:
            sys.stdout.buffer.write(active_frame if active else transparent)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            return

        deadline += interval
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -interval:
            deadline = time.monotonic()


if __name__ == "__main__":
    main()

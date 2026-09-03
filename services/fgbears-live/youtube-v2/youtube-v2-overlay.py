#!/usr/bin/env python3
"""FGB YouTube v2 exact-question-box overlay renderer.

This process has one job: emit a 798x470 RGBA frame at 10 fps. It is fully
transparent outside the authoritative trivia question phase and fully opaque
during the question phase. The routing contract must identify the exact source
question rectangle x=462,y=104,w=798,h=470 on the 1280x720 master canvas.

No legacy routing daemon, compositor, watchdog, cache, FIFO, or fallback relay
is used by this renderer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import urllib.request

import qrcode
from PIL import Image, ImageDraw, ImageFont

WIDTH = 798
HEIGHT = 470
FPS = 10.0
POLL_SECONDS = 0.20
ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
STATE_FILE = Path(os.getenv("YOUTUBE_V2_STATE_FILE", "/run/fgbears-youtube-v2/overlay-state.json"))
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
RUMBLE_URL = "https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html"
RUMBLE_DISPLAY = "rumble.com/v7eqrsu"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size=size)


def fetch() -> dict:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-YouTube-v2/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=1.5) as response:
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
        actual = region.get(key)
        if actual != expected:
            raise ValueError(f"mask contract mismatch: {key}={actual!r}, expected {expected!r}")
    if trivia.get("youtubeCreativeKey") != EXPECTED_CREATIVE:
        raise ValueError("unexpected youtubeCreativeKey")
    return trivia


def is_question(trivia: dict) -> bool:
    return str(trivia.get("phase") or "").strip().lower() == "question"


def build_active_frame() -> bytes:
    # Build the approved redirect creative on its native 1280x720 design canvas,
    # then fit it into the exact 798x470 question rectangle.
    w, h = 1280, 720
    bg = "#0B162A"
    orange = "#C83803"
    bottom = "#07101F"
    white = "#FFFFFF"
    muted = "#D5D9E2"
    gold = "#F2B134"

    image = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w, 93), fill=orange)
    draw.rectangle((0, 624, w, h - 1), fill=bottom)
    draw.rectangle((18, 18, w - 18, h - 18), outline=orange, width=5)
    draw.text((72, 30), "YOUTUBE VIEWERS", font=font(30, True), fill=white)
    draw.text((72, 146), "TRIVIA IS LIVE", font=font(66, True), fill=white)
    draw.text((72, 224), "ON RUMBLE", font=font(82, True), fill=orange)
    draw.text((76, 334), "PLAY NOW FOR CASH PRIZES", font=font(31, True), fill=gold)
    draw.text((76, 386), "Scan the QR code to join the live game.", font=font(27), fill=white)
    draw.text(
        (76, 428),
        "No purchase required. Eligibility and official rules apply.",
        font=font(20),
        fill=muted,
    )

    qr_card = (864, 122, 1204, 514)
    draw.rounded_rectangle(qr_card, radius=18, fill=white, outline=orange, width=5)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0)
    qr.add_data(RUMBLE_URL)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=bg, back_color=white).convert("RGB")
    qr_img = qr_img.resize((300, 300), Image.Resampling.NEAREST)
    image.paste(qr_img, (884, 142))

    label = "SCAN TO PLAY"
    label_font = font(24, True)
    bbox = draw.textbbox((0, 0), label, font=label_font)
    label_x = 864 + (340 - (bbox[2] - bbox[0])) // 2
    draw.text((label_x, 468), label, font=label_font, fill=bg)
    draw.text((72, 647), "OR VISIT", font=font(21, True), fill=muted)
    draw.text((230, 638), RUMBLE_DISPLAY, font=font(38, True), fill=white)

    source = image.convert("RGBA")
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (WIDTH, HEIGHT), (11, 22, 42, 255))
    out.paste(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2), source)
    return out.tobytes()


def write_state(*, ok: bool, phase: str, active: bool, last_good_epoch: float, error: str | None = None) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ok": ok,
            "phase": phase,
            "active": active,
            "lastGoodEpoch": last_good_epoch,
            "lastGoodAgeSeconds": max(0.0, time.time() - last_good_epoch) if last_good_epoch else None,
            "maskRegion": EXPECTED_REGION,
            "frameSize": [WIDTH, HEIGHT],
            "fps": FPS,
            "error": error,
        }
        fd, name = tempfile.mkstemp(prefix="overlay-state-", suffix=".json", dir=str(STATE_FILE.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(name, STATE_FILE)
    except Exception as exc:
        print(f"state write warning: {exc}", file=sys.stderr)


def self_test() -> int:
    active = build_active_frame()
    transparent = bytes(WIDTH * HEIGHT * 4)
    assert len(active) == WIDTH * HEIGHT * 4
    assert len(transparent) == WIDTH * HEIGHT * 4
    assert min(active[3::4]) == 255 and max(active[3::4]) == 255
    assert min(transparent[3::4]) == 0 and max(transparent[3::4]) == 0
    trivia = validate(fetch())
    print(
        json.dumps(
            {
                "ok": True,
                "phase": str(trivia.get("phase") or ""),
                "activeNow": is_question(trivia),
                "maskRegion": EXPECTED_REGION,
                "frameSize": [WIDTH, HEIGHT],
                "fps": FPS,
            },
            separators=(",", ":"),
        )
    )
    return 0


def stream() -> int:
    active_frame = build_active_frame()
    transparent = bytes(WIDTH * HEIGHT * 4)
    active = False
    phase = "unknown"
    last_good_epoch = 0.0
    last_poll = 0.0
    deadline = time.monotonic()
    interval = 1.0 / FPS

    # Require a valid contract before first output. If the API is temporarily
    # unavailable, retry without ever emitting an incorrectly placed cover.
    for attempt in range(60):
        try:
            trivia = validate(fetch())
            phase = str(trivia.get("phase") or "")
            active = is_question(trivia)
            last_good_epoch = time.time()
            write_state(ok=True, phase=phase, active=active, last_good_epoch=last_good_epoch)
            break
        except Exception as exc:
            if attempt == 59:
                write_state(ok=False, phase=phase, active=active, last_good_epoch=last_good_epoch, error=str(exc))
                raise
            time.sleep(0.5)

    while True:
        now = time.monotonic()
        if now - last_poll >= POLL_SECONDS:
            try:
                trivia = validate(fetch())
                phase = str(trivia.get("phase") or "")
                active = is_question(trivia)
                last_good_epoch = time.time()
                write_state(ok=True, phase=phase, active=active, last_good_epoch=last_good_epoch)
            except Exception as exc:
                # Fail closed only while already covering a question. If the
                # control plane drops during a question, keep the exact box
                # covered until a valid non-question state is received.
                write_state(
                    ok=False,
                    phase=phase,
                    active=active,
                    last_good_epoch=last_good_epoch,
                    error=str(exc),
                )
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

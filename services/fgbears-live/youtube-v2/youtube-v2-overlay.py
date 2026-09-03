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
- the mask geometry is fixed to the production game/ad panel;
- the locked Rumble redirect card is self-contained and needs no QR package.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

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

# Locked QR matrix for the canonical Rumble trivia URL. This is deliberately
# compiled into the production worker so Oracle does not need python-qrcode.
_REDIRECT_QR = (
    "11111110101110000110000001100010001111111",
    "10000010000010110000011010000010101000001",
    "10111010111100010100101111010101001011101",
    "10111010001110111000001000000111001011101",
    "10111010010000010100001011001110001011101",
    "10000010101100001100011010101100101000001",
    "11111110101010101010101010101010101111111",
    "00000000001110011001101010110000100000000",
    "10100011001001110001000110111000000100101",
    "01100101001000101111111101011011101000101",
    "11111111000000101111010101011011011011111",
    "00111100010101101010001010101001101011011",
    "00111010000101001001100000001000111100011",
    "11101000101011110100101000001101101100011",
    "11111110111011101110101101001101111000001",
    "10001100100110100011101000111010111001010",
    "00100011010011101000000110000001111001001",
    "10010100110010001111100111111101011101001",
    "01011110001011000001111100010101111111001",
    "01000001011001100100001101001000010001010",
    "01111111110110101101011111010111101101000",
    "10010001101011111001101111011001001101101",
    "01101110111011101011000110011101000000101",
    "00101100010010000010000110010011110101001",
    "10001110100000001000001110011000111001010",
    "00110101010111010011101111011001011101011",
    "00110010011001000111010101011101000101101",
    "01111001010110111010100110010011101001010",
    "10110010011001110011000010010000001100001",
    "01111100010011001100011010000101101100101",
    "11010011011000100011011010110111110011101",
    "00010101100010000000000110100010001011010",
    "11100010011001110001001010110000111111000",
    "00000000100011100001110110011101100011001",
    "11111110111101101111000101111000101010111",
    "10000010000000101010110010111100100011010",
    "10111010001001110110110001100101111110001",
    "10111010001101100111100110111100100111010",
    "10111010101001100001100100110101110011001",
    "10000010000000001111001000100010110001000",
    "11111110110101010111100010011000100011001",
)


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
            "User-Agent": "FGBears-YouTube-v2-Lovable/3.1",
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


def _redirect_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    if not path.is_file():
        raise FileNotFoundError(f"required redirect font missing: {path}")
    return ImageFont.truetype(str(path), size=size)


def _locked_qr_image() -> Image.Image:
    if len(_REDIRECT_QR) != 41 or any(len(row) != 41 for row in _REDIRECT_QR):
        raise RuntimeError("locked QR matrix is invalid")
    background = "#0B162A"
    qr = Image.new("RGB", (410, 410), "#FFFFFF")
    draw = ImageDraw.Draw(qr)
    for y, row in enumerate(_REDIRECT_QR):
        for x, bit in enumerate(row):
            if bit == "1":
                draw.rectangle((x * 10, y * 10, x * 10 + 9, y * 10 + 9), fill=background)
    return qr.resize((300, 300), Image.Resampling.NEAREST)


def build_locked_redirect() -> Image.Image:
    """Render the locked 1280x720 YouTube-to-Rumble redirect without qrcode."""
    width, height = 1280, 720
    background = "#0B162A"
    top_bar = "#C83803"
    bottom_bar = "#07101F"
    white = "#FFFFFF"
    muted = "#D5D9E2"
    gold = "#F2B134"

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, 93), fill=top_bar)
    draw.rectangle((0, 624, width, height - 1), fill=bottom_bar)
    draw.rectangle((18, 18, width - 18, height - 18), outline=top_bar, width=5)

    draw.text((72, 30), "YOUTUBE VIEWERS", font=_redirect_font(30, True), fill=white)
    draw.text((72, 146), "TRIVIA IS LIVE", font=_redirect_font(66, True), fill=white)
    draw.text((72, 224), "ON RUMBLE", font=_redirect_font(82, True), fill=top_bar)
    draw.text((76, 334), "PLAY NOW FOR CASH PRIZES", font=_redirect_font(31, True), fill=gold)
    draw.text(
        (76, 386),
        "Scan the QR code to join the live game.",
        font=_redirect_font(27),
        fill=white,
    )
    draw.text(
        (76, 428),
        "No purchase required. Eligibility and official rules apply.",
        font=_redirect_font(20),
        fill=muted,
    )

    qr_card = (864, 122, 1204, 514)
    draw.rounded_rectangle(qr_card, radius=18, fill=white, outline=top_bar, width=5)
    image.paste(_locked_qr_image(), (884, 142))

    label = "SCAN TO PLAY"
    label_font = _redirect_font(24, True)
    bbox = draw.textbbox((0, 0), label, font=label_font)
    label_x = 864 + (340 - (bbox[2] - bbox[0])) // 2
    draw.text((label_x, 468), label, font=label_font, fill=background)

    draw.text((72, 647), "OR VISIT", font=_redirect_font(21, True), fill=muted)
    draw.text((230, 638), "rumble.com/v7eqrsu", font=_redirect_font(38, True), fill=white)
    return image


def source_image_for(key: str) -> tuple[Image.Image, bool]:
    """Return source image and whether the locked background is required."""
    if key == BUILTIN_REDIRECT_KEY:
        return build_locked_redirect().convert("RGBA"), True
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

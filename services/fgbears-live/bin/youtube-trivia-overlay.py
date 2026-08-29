#!/usr/bin/env python3
"""YouTube-only full-screen Rumble trivia call-to-action.

The renderer follows the sanitized public game-screen feed. It publishes a
transparent RGBA frame when trivia is inactive and an opaque branded card when
``visible`` is true. Only the isolated YouTube relay consumes this renderer;
the primary program and Rumble copy-remux relay never do.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 720
PORT = int(os.getenv("YOUTUBE_TRIVIA_OVERLAY_PORT", "8790"))
FPS = max(1, min(5, int(os.getenv("YOUTUBE_TRIVIA_OVERLAY_FPS", "2"))))
POLL_SECONDS = max(1, int(os.getenv("YOUTUBE_TRIVIA_POLL_SECONDS", "2")))
STALE_SECONDS = max(5, int(os.getenv("YOUTUBE_TRIVIA_STALE_SECONDS", "10")))
FEED_URL = os.getenv(
    "GAME_SCREEN_FEED_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/game-screen",
)
FEED_FILE = os.getenv("GAME_SCREEN_FEED_FILE", "").strip()
RUMBLE_URL = os.getenv(
    "RUMBLE_TRIVIA_URL",
    "https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html",
)
RUMBLE_DISPLAY_URL = os.getenv("RUMBLE_TRIVIA_DISPLAY_URL", "rumble.com/v7eqrsu")

BEARS_BLUE = "#0B162A"
DEEP_BLUE = "#07101F"
BEARS_ORANGE = "#C83803"
WHITE = "#FFFFFF"
MUTED = "#D5D9E2"
GOLD = "#F2B134"
FONT_REGULAR = os.getenv(
    "YOUTUBE_TRIVIA_FONT_REGULAR",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_BOLD = os.getenv(
    "YOUTUBE_TRIVIA_FONT_BOLD",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size=size)
    except OSError:
        return ImageFont.load_default()


def centered_x(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont, left: int, right: int) -> int:
    box = draw.textbbox((0, 0), text, font=text_font)
    return left + max(0, (right - left - (box[2] - box[0])) // 2)


def qr_for(url: str, size: int) -> Image.Image | None:
    if not url:
        return None
    try:
        encoded = subprocess.run(
            ["qrencode", "-t", "PNG", "-o", "-", "-s", "10", "-m", "4", url],
            check=True,
            capture_output=True,
            timeout=5,
        ).stdout
        return Image.open(io.BytesIO(encoded)).convert("RGB").resize(
            (size, size), Image.Resampling.NEAREST
        )
    except Exception:
        return None


def load_payload() -> dict[str, Any]:
    if FEED_FILE:
        payload = json.loads(Path(FEED_FILE).read_text(encoding="utf-8"))
    else:
        parsed = urllib.parse.urlsplit(FEED_URL)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("_ts", str(int(time.time()))))
        fresh_url = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
        )
        request = urllib.request.Request(
            fresh_url,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "User-Agent": "FGBears-YouTube-Trivia-Overlay/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("game-screen feed must return an object")
    return payload


class TriviaState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.feed_active = False
        self.last_good_refresh = 0.0
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        active_value = payload.get("visible")
        if active_value is None:
            active_value = payload.get("triviaActive", payload.get("active", False))
        with self.lock:
            self.feed_active = truthy(active_value)
            self.last_good_refresh = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[bool, float, str | None]:
        with self.lock:
            age = time.time() - self.last_good_refresh if self.last_good_refresh else float("inf")
            return bool(self.feed_active and age <= STALE_SECONDS), age, self.last_error


STATE = TriviaState()


def poll() -> None:
    while True:
        try:
            STATE.update(load_payload())
        except Exception as exc:
            # Fail transparent: a feed outage must never cover YouTube or stop a relay.
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def build_card() -> Image.Image:
    image = Image.new("RGBA", (WIDTH, HEIGHT), BEARS_BLUE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 94), fill=BEARS_ORANGE)
    draw.rectangle((0, HEIGHT - 96, WIDTH, HEIGHT), fill=DEEP_BLUE)
    draw.rectangle((18, 18, WIDTH - 19, HEIGHT - 19), outline=BEARS_ORANGE, width=5)

    eyebrow = "YOUTUBE VIEWERS"
    eyebrow_font = font(30, bold=True)
    draw.text((72, 30), eyebrow, font=eyebrow_font, fill=WHITE)

    title_one = "TRIVIA IS LIVE"
    title_two = "ON RUMBLE"
    draw.text((72, 146), title_one, font=font(66, bold=True), fill=WHITE)
    draw.text((72, 224), title_two, font=font(82, bold=True), fill=BEARS_ORANGE)
    draw.text((76, 334), "PLAY NOW FOR CASH PRIZES", font=font(31, bold=True), fill=GOLD)
    draw.text((76, 386), "Scan the QR code to join the live game.", font=font(27), fill=WHITE)
    draw.text((76, 428), "No purchase required. Eligibility and official rules apply.", font=font(20), fill=MUTED)

    qr_size = 300
    qr_x, qr_y = 884, 142
    draw.rounded_rectangle(
        (qr_x - 20, qr_y - 20, qr_x + qr_size + 20, qr_y + qr_size + 72),
        radius=22,
        fill=WHITE,
        outline=BEARS_ORANGE,
        width=5,
    )
    qr = qr_for(RUMBLE_URL, qr_size)
    if qr is not None:
        image.paste(qr.convert("RGBA"), (qr_x, qr_y))
    else:
        draw.text((qr_x + 58, qr_y + 126), "QR", font=font(48, bold=True), fill=BEARS_BLUE)
    scan_text = "SCAN TO PLAY"
    scan_font = font(24, bold=True)
    draw.text(
        (centered_x(draw, scan_text, scan_font, qr_x, qr_x + qr_size), qr_y + qr_size + 24),
        scan_text,
        font=scan_font,
        fill=BEARS_BLUE,
    )

    visit = "OR VISIT"
    visit_font = font(21, bold=True)
    url_font = font(38, bold=True)
    draw.text((72, HEIGHT - 73), visit, font=visit_font, fill=MUTED)
    draw.text((230, HEIGHT - 82), RUMBLE_DISPLAY_URL, font=url_font, fill=WHITE)
    return image


TRANSPARENT_BYTES = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0)).tobytes()
CARD_IMAGE = build_card()
CARD_BYTES = CARD_IMAGE.tobytes()


def frame_bytes() -> bytes:
    active, _age, _error = STATE.snapshot()
    return CARD_BYTES if active else TRANSPARENT_BYTES


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsYouTubeTriviaOverlay/1.0"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            active, age, error = STATE.snapshot()
            body = json.dumps(
                {
                    "ok": True,
                    "active": active,
                    "lastGoodAgeSeconds": None if age == float("inf") else round(age, 3),
                    "lastError": error,
                    "renderer": "pillow-rgba",
                    "targetPlatform": "youtube",
                    "sourcePlatform": "rumble",
                    "fps": FPS,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/frame.png"):
            active, _age, _error = STATE.snapshot()
            output = io.BytesIO()
            (CARD_IMAGE if active else Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))).save(
                output, format="PNG"
            )
            body = output.getvalue()
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/overlay.rgba"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        interval = 1.0 / FPS
        next_frame_at = time.monotonic()
        try:
            while True:
                self.wfile.write(frame_bytes())
                self.wfile.flush()
                next_frame_at += interval
                delay = next_frame_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -interval:
                    next_frame_at = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    try:
        STATE.update(load_payload())
    except Exception as exc:
        STATE.error(exc)
    threading.Thread(target=poll, name="fgb-youtube-trivia-poller", daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Poll the EPIC admin crawl feed and serve a transparent lower-third ticker."""
from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FEED_URL = os.getenv("CRAWL_FEED_URL", "https://epiccontentcreatorgrants.org/api/public/fgbears/crawl")
FEED_FILE = os.getenv("CRAWL_FEED_FILE")
POLL_SECONDS = max(2, int(os.getenv("CRAWL_POLL_SECONDS", "5")))
PORT = int(os.getenv("CRAWL_OVERLAY_PORT", "8788"))
FPS = max(10, int(os.getenv("CRAWL_OVERLAY_FPS", "15")))
WIDTH, HEIGHT = 1280, 118
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size=size)
    except OSError:
        return ImageFont.load_default()


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.value: dict[str, Any] = {"active": False, "label": "EPIC LIVE", "message": "", "speed": "normal", "updatedAt": ""}
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        speed = str(payload.get("speed") or "normal").lower()
        if speed not in {"slow", "normal", "fast"}:
            speed = "normal"
        value = {
            "active": bool(payload.get("active")),
            "label": str(payload.get("label") or "EPIC LIVE")[:24],
            "message": str(payload.get("message") or "")[:280],
            "speed": speed,
            "updatedAt": str(payload.get("updatedAt") or ""),
        }
        with self.lock:
            self.value = value
            self.last_error = None

    def snapshot(self) -> tuple[dict[str, Any], str | None]:
        with self.lock:
            return dict(self.value), self.last_error


STATE = State()
STARTED = time.monotonic()


def poll() -> None:
    while True:
        try:
            STATE.update(load_feed())
        except Exception as exc:
            with STATE.lock:
                STATE.last_error = str(exc)
        time.sleep(POLL_SECONDS)


def load_feed() -> dict[str, Any]:
    if FEED_FILE:
        with open(FEED_FILE, encoding="utf-8") as source:
            return json.load(source)
    req = urllib.request.Request(FEED_URL, headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "FGBears-Live/1.0"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def frame() -> Image.Image:
    value, _ = STATE.snapshot()
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not value["active"] or not value["message"]:
        return image
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(7, 16, 31, 242))
    draw.rectangle((0, 0, WIDTH, 7), fill=(200, 56, 3, 255))
    label_width = 228
    draw.polygon([(0, 7), (label_width, 7), (label_width + 38, HEIGHT), (0, HEIGHT)], fill=(200, 56, 3, 255))
    label_font = font(29, bold=True)
    label = value["label"].upper()
    label_box = draw.textbbox((0, 0), label, font=label_font)
    draw.text(((label_width - (label_box[2] - label_box[0])) / 2, 42), label, font=label_font, fill="white")

    message_font = font(31, bold=True)
    message = value["message"].upper()
    text_width = draw.textbbox((0, 0), message, font=message_font)[2]
    speeds = {"slow": 70, "normal": 105, "fast": 150}
    pixels_per_second = speeds[value["speed"]]
    viewport_start = label_width + 55
    viewport_width = WIDTH - viewport_start
    cycle = viewport_width + text_width + 120
    x = viewport_width - ((time.monotonic() - STARTED) * pixels_per_second % cycle)
    ticker = Image.new("RGBA", (viewport_width, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(ticker).text((x, 39), message, font=message_font, fill="white")
    image.alpha_composite(ticker, (viewport_start, 0))
    return image


def png() -> bytes:
    output = io.BytesIO()
    frame().save(output, format="PNG")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            value, error = STATE.snapshot()
            body = json.dumps({"ok": True, "active": value["active"], "lastError": error}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/frame.png"):
            body = png()
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
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        try:
            while True:
                self.wfile.write(frame().tobytes())
                self.wfile.flush()
                time.sleep(1 / FPS)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    try:
        STATE.update(load_feed())
    except Exception:
        pass
    threading.Thread(target=poll, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

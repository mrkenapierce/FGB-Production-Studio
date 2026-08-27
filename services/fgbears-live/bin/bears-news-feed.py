#!/usr/bin/env python3
"""Poll the FGB-owned Bears RSS feed and render a sharp upper-third news ribbon."""
from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FEED_URL = os.getenv(
    "BEARS_NEWS_FEED_URL",
    "https://raw.githubusercontent.com/mrkenapierce/FGB-Production-Studio/main/feeds/fgb-bears-news.xml",
)
FEED_FILE = os.getenv("BEARS_NEWS_FEED_FILE")
LOCAL_FEED_FILE = Path(
    os.getenv("BEARS_NEWS_LOCAL_FEED_FILE", "/srv/fgbears-live/runtime/fgb-bears-news.xml")
)
POLL_SECONDS = max(30, int(os.getenv("BEARS_NEWS_POLL_SECONDS", "300")))
MAX_ITEMS = max(1, min(20, int(os.getenv("BEARS_NEWS_MAX_ITEMS", "8"))))
PORT = int(os.getenv("BEARS_NEWS_OVERLAY_PORT", "8789"))
FPS = max(10, int(os.getenv("BEARS_NEWS_OVERLAY_FPS", "30")))
SCROLL_PPS = max(20, int(os.getenv("BEARS_NEWS_SCROLL_PPS", "76")))
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))
SEPARATOR = "     ◆     "

WIDTH, HEIGHT = 1280, 104
PANEL_LEFT, PANEL_TOP = 18, 18
PANEL_RIGHT, PANEL_BOTTOM = 1261, 95
LABEL_RIGHT = 261
DIVIDER_LEFT, DIVIDER_RIGHT = 262, 266
VIEWPORT_LEFT, VIEWPORT_TOP = 267, 23
VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 990, 68
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BEARS_BLUE = (11, 22, 42, 255)
LANE_BLUE = (7, 16, 31, 252)
BEARS_ORANGE = (200, 56, 3, 255)
WHITE = (255, 255, 255, 255)


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size=size)
    except OSError:
        return ImageFont.load_default()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.replace(temporary, path)


def normalize(value: str | None) -> str:
    return " ".join((value or "").replace("\n", " ").split())


def source_name(item: ET.Element) -> str:
    source = item.find("source")
    if source is not None and normalize(source.text):
        return normalize(source.text)
    link = normalize(item.findtext("link"))
    host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
    return host or "FGB SOURCE"


def cache_busted_feed_url() -> str:
    parts = urllib.parse.urlsplit(FEED_URL)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.append(("_refresh", str(time.time_ns())))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))


def read_feed_bytes() -> bytes:
    if FEED_FILE:
        return Path(FEED_FILE).read_bytes()
    # Oracle's locally refreshed feed is the live source. GitHub remains the
    # canonical fallback before the first successful local scan.
    if LOCAL_FEED_FILE.is_file() and LOCAL_FEED_FILE.stat().st_size > 0:
        return LOCAL_FEED_FILE.read_bytes()
    request = urllib.request.Request(
        cache_busted_feed_url(),
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Cache-Control": "no-cache",
            "User-Agent": "FGBears-Live-News/5.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def load_message() -> str:
    root = ET.fromstring(read_feed_bytes())
    messages: list[str] = []
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        title = normalize(item.findtext("title"))
        if not title:
            continue
        category = normalize(item.findtext("category")).lower()
        prefix = "BREAKING: " if category == "breaking" else ""
        source = source_name(item)
        messages.append(f"{prefix}{title}  •  SOURCE: {source}")
    return SEPARATOR.join(messages)


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.message = ""
        self.started = time.monotonic()
        self.last_error: str | None = None

    def update(self, message: str) -> None:
        message = normalize(message)
        with self.lock:
            if message != self.message:
                self.message = message
                self.started = time.monotonic()
            self.last_error = None
        publish(message)

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[str, float, str | None]:
        with self.lock:
            return self.message, self.started, self.last_error


STATE = State()


def publish(message: str) -> None:
    active = bool(message)
    atomic_text(RUNTIME_DIR / "bears-news-label.txt", "BEARS NEWS" if active else "")
    atomic_text(RUNTIME_DIR / "bears-news-message.txt", message.upper() if active else "")
    atomic_text(RUNTIME_DIR / "bears-news-active", "1" if active else "0")


def poll() -> None:
    while True:
        try:
            refreshed = load_message()
            if refreshed:
                STATE.update(refreshed)
            else:
                current, _, _ = STATE.snapshot()
                if not current:
                    STATE.update("")
        except Exception as exc:
            # Keep the last good ribbon during transient source/network failures.
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def text_bbox(text: str, text_font: ImageFont.ImageFont) -> tuple[int, int, int, int]:
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return ImageDraw.Draw(probe).textbbox((0, 0), text, font=text_font)


def frame(now: float | None = None) -> Image.Image:
    if now is None:
        now = time.monotonic()
    message, started, _ = STATE.snapshot()
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if not message:
        return image

    # Recreate the production upper ribbon as pixels before FFmpeg sees it.
    # This removes drawtext/crop boundary interactions that could destroy glyph
    # strokes while retaining the existing Bears-blue/orange geometry.
    draw = ImageDraw.Draw(image)
    draw.rectangle((7, 7, 1272, 103), fill=BEARS_BLUE)
    draw.rectangle((PANEL_LEFT, PANEL_TOP, PANEL_RIGHT, PANEL_BOTTOM), fill=LANE_BLUE)
    draw.rectangle((PANEL_LEFT, PANEL_TOP, LABEL_RIGHT, PANEL_BOTTOM), fill=BEARS_ORANGE)
    draw.rectangle((PANEL_LEFT, PANEL_TOP, PANEL_RIGHT, PANEL_TOP + 4), fill=BEARS_ORANGE)
    draw.rectangle((PANEL_LEFT, PANEL_BOTTOM - 4, PANEL_RIGHT, PANEL_BOTTOM), fill=BEARS_ORANGE)
    draw.rectangle((PANEL_LEFT, PANEL_TOP, PANEL_LEFT + 4, PANEL_BOTTOM), fill=BEARS_ORANGE)
    draw.rectangle((PANEL_RIGHT - 4, PANEL_TOP, PANEL_RIGHT, PANEL_BOTTOM), fill=BEARS_ORANGE)
    draw.rectangle((DIVIDER_LEFT, VIEWPORT_TOP, DIVIDER_RIGHT, VIEWPORT_TOP + VIEWPORT_HEIGHT - 1), fill=BEARS_ORANGE)

    label = "BEARS NEWS"
    label_font = font(29, bold=True)
    label_box = draw.textbbox((0, 0), label, font=label_font)
    label_width = label_box[2] - label_box[0]
    label_height = label_box[3] - label_box[1]
    label_x = PANEL_LEFT + (LABEL_RIGHT - PANEL_LEFT + 1 - label_width) / 2
    label_y = PANEL_TOP + (PANEL_BOTTOM - PANEL_TOP + 1 - label_height) / 2 - label_box[1]
    draw.text((label_x, label_y), label, font=label_font, fill=WHITE)

    message = message.upper().strip()
    message_font = font(31, bold=True)
    message_box = text_bbox(message, message_font)
    text_width = max(1, message_box[2] - message_box[0])
    text_height = message_box[3] - message_box[1]
    elapsed = max(0.0, now - started)
    cycle = VIEWPORT_WIDTH + text_width
    x = VIEWPORT_WIDTH - ((elapsed * SCROLL_PPS) % cycle)
    y = (VIEWPORT_HEIGHT - text_height) / 2 - message_box[1]

    # Rasterize the entire headline with Pillow, then clip the finished pixels to
    # the message lane. FFmpeg only composites this image; it no longer shapes,
    # reloads, crops, or scrolls individual news glyphs.
    ticker = Image.new("RGBA", (VIEWPORT_WIDTH, VIEWPORT_HEIGHT), (0, 0, 0, 0))
    ticker_draw = ImageDraw.Draw(ticker)
    ticker_draw.text((int(x), y), message, font=message_font, fill=WHITE)
    image.alpha_composite(ticker, (VIEWPORT_LEFT, VIEWPORT_TOP))
    return image


def jpeg() -> bytes:
    output = io.BytesIO()
    frame().convert("RGB").save(
        output,
        format="JPEG",
        quality=100,
        subsampling=0,
        optimize=False,
    )
    return output.getvalue()


def png() -> bytes:
    output = io.BytesIO()
    frame().save(output, format="PNG")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsNewsOverlay/5.0"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            message, _, error = STATE.snapshot()
            body = json.dumps(
                {
                    "ok": True,
                    "active": bool(message),
                    "lastError": error,
                    "renderer": "pillow-mjpeg",
                    "messageChars": len(message),
                    "fps": FPS,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
        if self.path.startswith("/frame.jpg"):
            body = jpeg()
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/overlay.mjpg"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        interval = 1.0 / FPS
        next_frame_at = time.monotonic()
        try:
            while True:
                body = jpeg()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
                self.wfile.write(body)
                self.wfile.write(b"\r\n")
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
        STATE.update(load_message())
    except Exception as exc:
        STATE.error(exc)
        publish("")
    threading.Thread(target=poll, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

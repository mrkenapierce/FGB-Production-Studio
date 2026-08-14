#!/usr/bin/env python3
"""Poll the FGB-owned Bears RSS feed and serve a clipped upper-third news strip."""
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
POLL_SECONDS = max(30, int(os.getenv("BEARS_NEWS_POLL_SECONDS", "300")))
MAX_ITEMS = max(1, min(20, int(os.getenv("BEARS_NEWS_MAX_ITEMS", "8"))))
PORT = int(os.getenv("BEARS_NEWS_OVERLAY_PORT", "8789"))
FPS = max(10, int(os.getenv("BEARS_NEWS_OVERLAY_FPS", "15")))
STATIC_SECONDS = max(8, int(os.getenv("BEARS_NEWS_STATIC_SECONDS", "18")))
SCROLL_PPS = max(50, int(os.getenv("BEARS_NEWS_SCROLL_PPS", "90")))
SCROLL_END_HOLD = 1.5
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))

WIDTH, HEIGHT = 1244, 78
OUTER_BORDER = 5
LABEL_RIGHT = 230
VIEWPORT_START = LABEL_RIGHT + 1
VIEWPORT_RIGHT = WIDTH - OUTER_BORDER - 1
VIEWPORT_WIDTH = VIEWPORT_RIGHT - VIEWPORT_START + 1
TEXT_PAD = 12
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BEARS_BLUE = (11, 22, 42, 250)
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


def read_feed_bytes() -> bytes:
    if FEED_FILE:
        return Path(FEED_FILE).read_bytes()
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Cache-Control": "no-cache",
            "User-Agent": "FGBears-Live-News/2.1",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def load_items() -> list[dict[str, str]]:
    root = ET.fromstring(read_feed_bytes())
    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        title = normalize(item.findtext("title"))
        if not title:
            continue
        category = normalize(item.findtext("category")).lower()
        label = "BREAKING BEARS" if category == "breaking" else "BEARS NEWS"
        source = source_name(item)
        # Preserve the full FGB headline and complete source string. The renderer
        # masks the moving text behind the orange label instead of truncating it.
        items.append({"label": label, "message": f"{title}  •  SOURCE: {source}"})
    return items


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: list[dict[str, str]] = []
        self.index = 0
        self.display_started = time.monotonic()
        self.last_error: str | None = None

    def replace_items(self, items: list[dict[str, str]]) -> None:
        with self.lock:
            current = self.items[self.index]["message"] if self.items else None
            self.items = items
            if not items:
                self.index = 0
                self.display_started = time.monotonic()
                self.last_error = None
                publish_text(None)
                return
            if current:
                for idx, item in enumerate(items):
                    if item["message"] == current:
                        self.index = idx
                        break
                else:
                    self.index = 0
                    self.display_started = time.monotonic()
            else:
                self.index = 0
                self.display_started = time.monotonic()
            self.last_error = None
            publish_text(self.items[self.index])

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[dict[str, str] | None, float, str | None]:
        with self.lock:
            item = dict(self.items[self.index]) if self.items else None
            return item, self.display_started, self.last_error

    def advance_if_due(self, duration: float) -> None:
        with self.lock:
            if not self.items:
                return
            if time.monotonic() - self.display_started < duration:
                return
            self.index = (self.index + 1) % len(self.items)
            self.display_started = time.monotonic()
            publish_text(self.items[self.index])


STATE = State()


def publish_text(item: dict[str, str] | None) -> None:
    if item is None:
        atomic_text(RUNTIME_DIR / "bears-news-label.txt", "")
        atomic_text(RUNTIME_DIR / "bears-news-message.txt", "")
        atomic_text(RUNTIME_DIR / "bears-news-active", "0")
        return
    atomic_text(RUNTIME_DIR / "bears-news-label.txt", item["label"].upper())
    atomic_text(RUNTIME_DIR / "bears-news-message.txt", item["message"].upper())
    atomic_text(RUNTIME_DIR / "bears-news-active", "1")


def poll() -> None:
    while True:
        try:
            refreshed = load_items()
            if refreshed:
                STATE.replace_items(refreshed)
            else:
                item, _, _ = STATE.snapshot()
                if item is None:
                    STATE.replace_items([])
        except Exception as exc:
            # Keep the last good feed during transient network failures.
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def text_bbox(message: str, message_font: ImageFont.ImageFont) -> tuple[int, int, int, int]:
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return ImageDraw.Draw(probe).textbbox((0, 0), message, font=message_font)


def text_metrics(message: str) -> tuple[ImageFont.ImageFont, int, int]:
    message_font = font(25, bold=True)
    bbox = text_bbox(message, message_font)
    return message_font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def centered_text_y(message: str, message_font: ImageFont.ImageFont) -> float:
    bbox = text_bbox(message, message_font)
    text_height = bbox[3] - bbox[1]
    return (HEIGHT - text_height) / 2 - bbox[1]


def scroll_travel(text_width: int) -> float:
    # Text starts just behind the orange right border and continues until the
    # final character is fully hidden beneath the orange BEARS NEWS label.
    return float(VIEWPORT_WIDTH + text_width)


def display_duration(message: str) -> float:
    _, text_width, _ = text_metrics(message)
    if text_width <= VIEWPORT_WIDTH - 2 * TEXT_PAD:
        return float(STATIC_SECONDS)
    return max(float(STATIC_SECONDS), scroll_travel(text_width) / SCROLL_PPS + SCROLL_END_HOLD)


def headline_x(text_width: int, elapsed: float) -> float:
    if text_width <= VIEWPORT_WIDTH - 2 * TEXT_PAD:
        return float(VIEWPORT_START + TEXT_PAD)
    # Each RSS item starts outside the right interior edge. It then passes
    # continuously behind the fixed orange label; there is no blue clipping gap.
    return float(WIDTH - OUTER_BORDER) - max(0.0, elapsed) * SCROLL_PPS


def draw_outer_border(draw: ImageDraw.ImageDraw) -> None:
    # Paint four exact-width rectangles rather than a stroked outline so every
    # side is the same Chicago Bears Orange thickness in the encoded stream.
    draw.rectangle((0, 0, WIDTH - 1, OUTER_BORDER - 1), fill=BEARS_ORANGE)
    draw.rectangle((0, HEIGHT - OUTER_BORDER, WIDTH - 1, HEIGHT - 1), fill=BEARS_ORANGE)
    draw.rectangle((0, 0, OUTER_BORDER - 1, HEIGHT - 1), fill=BEARS_ORANGE)
    draw.rectangle((WIDTH - OUTER_BORDER, 0, WIDTH - 1, HEIGHT - 1), fill=BEARS_ORANGE)


def frame() -> Image.Image:
    item, started, _ = STATE.snapshot()
    image = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    if item is None:
        return image

    message = item["message"].upper()
    STATE.advance_if_due(display_duration(message))
    item, started, _ = STATE.snapshot()
    if item is None:
        return image
    message = item["message"].upper()

    # Build a true orange frame first, then fill only its interior blue.
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=BEARS_ORANGE)
    draw.rectangle(
        (OUTER_BORDER, OUTER_BORDER, WIDTH - 1 - OUTER_BORDER, HEIGHT - 1 - OUTER_BORDER),
        fill=BEARS_BLUE,
    )

    message_font, text_width, _ = text_metrics(message)
    text_y = centered_text_y(message, message_font)
    elapsed = max(0.0, time.monotonic() - started)

    # Draw the entire moving headline first. The fixed orange label is painted
    # afterward, so the headline visibly disappears underneath orange—not at a
    # blue clipping line. The outer border is also repainted last.
    ticker = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ticker_draw = ImageDraw.Draw(ticker)
    ticker_draw.text((headline_x(text_width, elapsed), text_y), message, font=message_font, fill=WHITE)
    image.alpha_composite(ticker)

    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (OUTER_BORDER, OUTER_BORDER, LABEL_RIGHT, HEIGHT - 1 - OUTER_BORDER),
        fill=BEARS_ORANGE,
    )

    label_font = font(24, bold=True)
    label = item["label"].upper()
    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_w = label_bbox[2] - label_bbox[0]
    label_h = label_bbox[3] - label_bbox[1]
    label_y = (HEIGHT - label_h) / 2 - label_bbox[1]
    label_center = (OUTER_BORDER + LABEL_RIGHT) / 2
    draw.text((label_center - label_w / 2, label_y), label, font=label_font, fill=WHITE)

    draw_outer_border(draw)
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
            item, _, error = STATE.snapshot()
            body = json.dumps({"ok": True, "active": item is not None, "label": item["label"] if item else "", "lastError": error}).encode()
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
        STATE.replace_items(load_items())
    except Exception as exc:
        STATE.error(exc)
        publish_text(None)
    threading.Thread(target=poll, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

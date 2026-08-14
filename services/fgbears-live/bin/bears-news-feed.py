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
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))

WIDTH, HEIGHT = 1244, 78
OUTER_BORDER = 4
LABEL_WIDTH = 230
LABEL_GAP = 18
VIEWPORT_START = LABEL_WIDTH + LABEL_GAP
VIEWPORT_RIGHT_PAD = 12
VIEWPORT_WIDTH = WIDTH - VIEWPORT_START - VIEWPORT_RIGHT_PAD
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
            "User-Agent": "FGBears-Live-News/2.0",
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
        # clips and scrolls the viewport instead of truncating editorial text.
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


def text_metrics(message: str) -> tuple[ImageFont.ImageFont, int, int]:
    message_font = font(25, bold=True)
    probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    bbox = draw.textbbox((0, 0), message, font=message_font)
    return message_font, bbox[2] - bbox[0], bbox[3] - bbox[1]


def display_duration(message: str) -> float:
    _, text_width, _ = text_metrics(message)
    if text_width <= VIEWPORT_WIDTH - 8:
        return float(STATIC_SECONDS)
    # One complete pass: enter from the right, cross the viewport, and fully
    # disappear behind the left clipping edge before the next item can begin.
    travel = VIEWPORT_WIDTH + text_width + 80
    return max(float(STATIC_SECONDS), travel / SCROLL_PPS + 1.5)


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

    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), fill=BEARS_BLUE)
    # Chicago Bears Orange border on all four sides.
    draw.rectangle(
        (OUTER_BORDER // 2, OUTER_BORDER // 2, WIDTH - 1 - OUTER_BORDER // 2, HEIGHT - 1 - OUTER_BORDER // 2),
        outline=BEARS_ORANGE,
        width=OUTER_BORDER,
    )

    # Fixed label panel remains separate from the clipped headline viewport.
    draw.rectangle((OUTER_BORDER, OUTER_BORDER, LABEL_WIDTH, HEIGHT - 1 - OUTER_BORDER), fill=BEARS_ORANGE)
    label_font = font(24, bold=True)
    label = item["label"].upper()
    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_w = label_bbox[2] - label_bbox[0]
    label_h = label_bbox[3] - label_bbox[1]
    label_y = (HEIGHT - label_h) / 2 - label_bbox[1]
    draw.text(((LABEL_WIDTH - label_w) / 2, label_y), label, font=label_font, fill=WHITE)

    message_font, text_width, text_height = text_metrics(message)
    text_y = (HEIGHT - text_height) / 2
    elapsed = max(0.0, time.monotonic() - started)

    ticker = Image.new("RGBA", (VIEWPORT_WIDTH, HEIGHT), (0, 0, 0, 0))
    ticker_draw = ImageDraw.Draw(ticker)
    if text_width <= VIEWPORT_WIDTH - 8:
        x = 4
    else:
        # Reset for every RSS item. Start at the right edge, scroll the complete
        # string through, then fully disappear at the left edge.
        x = VIEWPORT_WIDTH - elapsed * SCROLL_PPS
    ticker_draw.text((x, text_y), message, font=message_font, fill=WHITE)
    # alpha_composite clips anything outside ticker, reproducing the crawl's
    # clean disappear-into-frame behavior at both horizontal edges.
    image.alpha_composite(ticker, (VIEWPORT_START, 0))
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

#!/usr/bin/env python3
"""Poll the EPIC admin crawl feed and serve an emoji-safe lower-third ticker."""
from __future__ import annotations

import io
import json
import os
import threading
import time
import unicodedata
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FEED_URL = os.getenv("CRAWL_FEED_URL", "https://epiccontentcreatorgrants.org/api/public/fgbears/crawl")
FEED_FILE = os.getenv("CRAWL_FEED_FILE")
POLL_SECONDS = max(2, int(os.getenv("CRAWL_POLL_SECONDS", "5")))
PORT = int(os.getenv("CRAWL_OVERLAY_PORT", "8788"))
FPS = max(10, int(os.getenv("CRAWL_OVERLAY_FPS", "30")))
SPEED_SCALE = min(1.0, max(0.25, float(os.getenv("CRAWL_SPEED_SCALE", "0.72"))))
WIDTH, HEIGHT = 1280, 139
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))
EMOJI_CACHE_DIR = Path(os.getenv("CRAWL_EMOJI_CACHE_DIR", str(RUNTIME_DIR / "emoji-cache")))
EMOJI_CDN = os.getenv(
    "CRAWL_EMOJI_CDN",
    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72",
).rstrip("/")

BEARS_BLUE = (11, 22, 42, 255)
LANE_BLUE = (7, 16, 31, 255)
BEARS_ORANGE = (200, 56, 3, 255)
WHITE = (255, 255, 255, 255)

_EMOJI_IMAGES: dict[tuple[str, int], Image.Image | None] = {}
_EMOJI_FAILURE_AT: dict[str, float] = {}
_EMOJI_LOCK = threading.Lock()
_LINE_CACHE: dict[tuple[str, int, bool, int], tuple[Image.Image, int]] = {}
_LINE_CACHE_LOCK = threading.Lock()


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size=size)
    except OSError:
        return ImageFont.load_default()


def graphemes(text: str) -> list[str]:
    """Split text without breaking common emoji/ZWJ/flag/keycap sequences."""
    clusters: list[str] = []
    i = 0
    while i < len(text):
        cluster = text[i]
        cp = ord(text[i])
        i += 1
        if 0x1F1E6 <= cp <= 0x1F1FF and i < len(text):
            next_cp = ord(text[i])
            if 0x1F1E6 <= next_cp <= 0x1F1FF:
                cluster += text[i]
                i += 1
        while i < len(text):
            ch = text[i]
            cp = ord(ch)
            category = unicodedata.category(ch)
            if (
                cp in {0xFE0E, 0xFE0F, 0x20E3}
                or 0x1F3FB <= cp <= 0x1F3FF
                or 0xE0020 <= cp <= 0xE007F
                or category in {"Mn", "Mc", "Me"}
            ):
                cluster += ch
                i += 1
                continue
            if cp == 0x200D and i + 1 < len(text):
                cluster += ch + text[i + 1]
                i += 2
                continue
            break
        clusters.append(cluster)
    return clusters


def grapheme_slice(text: str, limit: int) -> str:
    return "".join(graphemes(text)[:limit])


def is_emoji_cluster(cluster: str) -> bool:
    for ch in cluster:
        cp = ord(ch)
        if (
            0x1F000 <= cp <= 0x1FAFF
            or 0x2600 <= cp <= 0x27BF
            or 0x2300 <= cp <= 0x23FF
            or 0x2B00 <= cp <= 0x2BFF
            or 0x2190 <= cp <= 0x21FF
            or 0x1F1E6 <= cp <= 0x1F1FF
            or cp in {0x00A9, 0x00AE, 0x203C, 0x2049, 0x20E3, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299}
        ):
            return True
    return False


def emoji_codes(cluster: str) -> list[str]:
    points = [ord(ch) for ch in cluster]
    full = "-".join(f"{cp:x}" for cp in points)
    stripped = "-".join(f"{cp:x}" for cp in points if cp != 0xFE0F)
    return list(dict.fromkeys(code for code in (full, stripped) if code))


def _download_emoji(code: str) -> Path | None:
    now = time.monotonic()
    if now - _EMOJI_FAILURE_AT.get(code, -10_000) < 300:
        return None
    EMOJI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = EMOJI_CACHE_DIR / f"{code}.png"
    if path.is_file():
        return path
    request = urllib.request.Request(
        f"{EMOJI_CDN}/{code}.png",
        headers={"Accept": "image/png", "Cache-Control": "max-age=31536000", "User-Agent": "FGBears-Live/1.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            body = response.read()
        probe = Image.open(io.BytesIO(body))
        probe.load()
        if probe.format != "PNG":
            raise ValueError("emoji asset is not PNG")
        temporary = path.with_suffix(".partial.png")
        temporary.write_bytes(body)
        os.replace(temporary, path)
        return path
    except Exception:
        _EMOJI_FAILURE_AT[code] = now
        return None


def emoji_image(cluster: str, size: int) -> Image.Image | None:
    if not is_emoji_cluster(cluster):
        return None
    for code in emoji_codes(cluster):
        key = (code, size)
        with _EMOJI_LOCK:
            if key in _EMOJI_IMAGES:
                cached = _EMOJI_IMAGES[key]
                if cached is not None:
                    return cached
                continue
        path = _download_emoji(code)
        image: Image.Image | None = None
        if path is not None:
            try:
                image = Image.open(path).convert("RGBA")
                image = image.resize((size, size), Image.Resampling.LANCZOS)
            except Exception:
                image = None
        with _EMOJI_LOCK:
            _EMOJI_IMAGES[key] = image
        if image is not None:
            return image
    return None


def text_width(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=text_font)
    return max(0, box[2] - box[0])


def rich_line(text: str, size: int, bold: bool = True, emoji_size: int | None = None) -> tuple[Image.Image, int]:
    emoji_px = emoji_size or size + 3
    key = (text, size, bold, emoji_px)
    with _LINE_CACHE_LOCK:
        cached = _LINE_CACHE.get(key)
        if cached is not None:
            return cached

    text_font = font(size, bold=bold)
    scratch = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    measure = ImageDraw.Draw(scratch)
    parts: list[tuple[str, str | Image.Image, int]] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        width = text_width(measure, buffer, text_font)
        parts.append(("text", buffer, width))
        buffer = ""

    for cluster in graphemes(text):
        icon = emoji_image(cluster, emoji_px)
        if icon is None:
            buffer += cluster
        else:
            flush()
            parts.append(("emoji", icon, emoji_px + 4))
    flush()

    width = max(1, sum(part[2] for part in parts))
    sample_box = measure.textbbox((0, 0), "Ag", font=text_font)
    text_height = sample_box[3] - sample_box[1]
    height = max(emoji_px + 8, text_height + 14)
    line = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(line)
    x = 0
    text_y = (height - text_height) // 2 - sample_box[1]
    emoji_y = (height - emoji_px) // 2
    for kind, payload, part_width in parts:
        if kind == "text":
            draw.text((x, text_y), str(payload), font=text_font, fill=WHITE)
        else:
            icon = payload
            assert isinstance(icon, Image.Image)
            line.paste(icon, (x + 2, emoji_y), icon)
        x += part_width

    result = (line, width)
    with _LINE_CACHE_LOCK:
        if len(_LINE_CACHE) > 64:
            _LINE_CACHE.clear()
        _LINE_CACHE[key] = result
    return result


def prime_emoji_cache(label: str, message: str) -> None:
    if label:
        rich_line(label.upper(), 29, True, 32)
    if message:
        rich_line(message.upper(), 31, True, 35)


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.value: dict[str, Any] = {
            "active": False,
            "label": "EPIC LIVE",
            "message": "",
            "messageCount": 0,
            "speed": "normal",
            "speedPps": 105,
            "updatedAt": "",
        }
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        speed = str(payload.get("speed") or "normal").lower()
        if speed not in {"slow", "normal", "fast"}:
            speed = "normal"
        fallback_pps = {"slow": 70, "normal": 105, "fast": 150}[speed]
        try:
            speed_pps = float(payload.get("speedPps") or fallback_pps)
        except (TypeError, ValueError):
            speed_pps = float(fallback_pps)
        speed_pps = min(400.0, max(20.0, speed_pps * SPEED_SCALE))
        label = grapheme_slice(str(payload.get("label") or "EPIC LIVE"), 24)
        trivia_mode = (
            bool(payload.get("triviaActive"))
            or str(payload.get("mode") or "").strip().casefold() == "trivia"
            or str(payload.get("type") or "").strip().casefold() == "trivia"
            or label.strip().casefold() == "trivia"
        )
        message_parts: list[str] = []
        raw_messages = payload.get("messages")
        if isinstance(raw_messages, list):
            for entry in raw_messages:
                if isinstance(entry, str):
                    enabled = True
                    text = entry
                elif isinstance(entry, dict):
                    enabled = bool(entry.get("enabled", True))
                    text = str(entry.get("text") or entry.get("message") or "")
                else:
                    continue
                normalized = grapheme_slice(" ".join(text.split()), 600)
                if enabled and normalized and "rockford zip showdown" not in normalized.casefold():
                    message_parts.append(normalized)
                if len(message_parts) == 5:
                    break
        separator = grapheme_slice(str(payload.get("separator") or "•"), 8) or "•"
        if message_parts:
            message = ("     " + separator + "     ").join(message_parts)
        else:
            message = grapheme_slice(str(payload.get("message") or ""), 600)
        message = grapheme_slice(message, 3200)
        if trivia_mode and not message_parts:
            # Safety fallback: legacy single-message trivia payloads may contain a
            # question prompt, so never route that fallback through the lower crawl.
            # The canonical trivia API now supplies a status-only messages[] array
            # (standings, daily leaderboard, participation, prize, progress), which
            # is safe and should remain visible in the Trivia crawl.
            message = ""
        message_count = len(message_parts) if message_parts else (0 if trivia_mode else (1 if message else 0))
        value = {
            "active": bool(payload.get("active")),
            "label": label,
            "message": message,
            "messages": message_parts if message_parts else ([message] if message else []),
            "messageCount": message_count,
            "speed": speed,
            "speedPps": speed_pps,
            "updatedAt": str(payload.get("updatedAt") or ""),
        }
        if value["active"] and (label or message):
            prime_emoji_cache(label, message)
        with self.lock:
            self.value = value
            self.last_error = None
        publish_text(value)

    def snapshot(self) -> tuple[dict[str, Any], str | None]:
        with self.lock:
            return dict(self.value), self.last_error


STATE = State()


class CrawlSequence:
    """Display each informational entry for one uninterrupted crawl pass."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.messages: list[str] = []
        self.current = ""
        self.index = 0
        self.started = time.monotonic()

    def select(self, value: dict[str, Any], now: float) -> tuple[str, float]:
        incoming = [str(item) for item in value.get("messages", []) if str(item).strip()]
        with self.lock:
            if not value["active"] or not incoming:
                self.messages = []
                self.current = ""
                self.index = 0
                self.started = now
            elif not self.current:
                self.messages = incoming
                self.index = 0
                self.current = incoming[0]
                self.started = now
            else:
                # Refresh future entries without changing the text or measured
                # width of the segment that is currently crossing the screen.
                self.messages = incoming
                self.index %= len(incoming)
            return self.current, self.started

    def advance_if_complete(self, x: float, text_width_px: int, now: float) -> bool:
        with self.lock:
            if not self.messages or x > -text_width_px:
                return False
            self.index = (self.index + 1) % len(self.messages)
            self.current = self.messages[self.index]
            self.started = now
            return True


SEQUENCE = CrawlSequence()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish_text(value: dict[str, Any]) -> None:
    active = bool(value["active"] and (value["label"] or value["message"]))
    label = value["label"].upper() if active else ""
    message = value["message"].upper().strip() if active else ""
    atomic_text(RUNTIME_DIR / "crawl-label.txt", label)
    atomic_text(RUNTIME_DIR / "crawl-message.txt", message)
    atomic_text(RUNTIME_DIR / "crawl-active", "1" if active else "0")


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
    req = urllib.request.Request(
        FEED_URL,
        headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "FGBears-Live/1.1"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def frame(now: float | None = None) -> Image.Image:
    if now is None:
        now = time.monotonic()
    value, _ = STATE.snapshot()
    message, started = SEQUENCE.select(value, now)
    image = Image.new("RGBA", (WIDTH, HEIGHT), BEARS_BLUE)
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 10, 1261, 128), fill=LANE_BLUE)
    draw.rectangle((18, 10, 261, 128), fill=BEARS_ORANGE)
    draw.rectangle((18, 10, 1261, 14), fill=BEARS_ORANGE)
    draw.rectangle((18, 123, 1261, 128), fill=BEARS_ORANGE)
    draw.rectangle((18, 10, 22, 128), fill=BEARS_ORANGE)
    draw.rectangle((1257, 10, 1261, 128), fill=BEARS_ORANGE)
    # Keep a single clean orange boundary between the label block and message lane.
    draw.rectangle((262, 15, 266, 122), fill=BEARS_ORANGE)

    if not value["active"]:
        return image

    label = value["label"].upper()
    label_line, label_width = rich_line(label, 29, True, 32)
    label_x = 18 + max(0, (239 - label_width) // 2)
    label_y = 10 + (118 - label_line.height) // 2
    image.paste(label_line, (label_x, label_y), label_line)

    if not message:
        return image

    message = message.upper().strip()
    message_line, text_width_px = rich_line(message, 31, True, 35)
    # Clip moving glyphs at the actual orange divider/right border so there is
    # no visible dark-blue receiving gutter at either end of the crawl.
    viewport_start = 267
    viewport_top = 15
    viewport_width = 990
    viewport_height = 108
    cycle = viewport_width + text_width_px + 120
    x = viewport_width - ((now - started) * float(value["speedPps"]) % cycle)
    if SEQUENCE.advance_if_complete(x, text_width_px, now):
        return frame(now)
    ticker = Image.new("RGBA", (viewport_width, viewport_height), (0, 0, 0, 0))
    line_y = (viewport_height - message_line.height) // 2
    ticker.paste(message_line, (int(x), line_y), message_line)
    image.alpha_composite(ticker, (viewport_start, viewport_top))
    return image


def jpeg() -> bytes:
    output = io.BytesIO()
    # Preserve sharp high-contrast crawl text and Bears orange/blue edges across
    # the localhost MJPEG transport. 4:4:4 avoids the chroma blockiness caused
    # by Pillow's default JPEG subsampling while keeping the renderer at 30 fps.
    frame().convert("RGB").save(
        output,
        format="JPEG",
        quality=96,
        subsampling=0,
        optimize=False,
    )
    return output.getvalue()


def png() -> bytes:
    output = io.BytesIO()
    frame().save(output, format="PNG")
    return output.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsCrawlOverlay/1.1"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            value, error = STATE.snapshot()
            body = json.dumps(
                {
                    "ok": True,
                    "active": value["active"],
                    "lastError": error,
                    "emojiRenderer": "twemoji-png",
                    "messageGraphemes": len(graphemes(str(value["message"]))),
                    "messageCount": int(value.get("messageCount") or 0),
                    "fps": FPS,
                    "transport": "rgba-loopback",
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
        if self.path.startswith("/overlay.mjpg"):
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

#!/usr/bin/env python3
"""High-quality deterministic wrapper for the FGB lower-third crawl renderer.

The production program remains 1280x720. This wrapper keeps that exact canvas,
timing, feed, emoji and sequencing contract, rasterizes crawl glyphs at 2x (or
CRAWL_TEXT_RENDER_SCALE), and guarantees that the segment already crossing the
screen completes before a refreshed payload replaces the sequence.
"""
from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "crawl-overlay.py"
spec = importlib.util.spec_from_file_location("fgbears_crawl_overlay_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load crawl renderer: {BASE_PATH}")
BASE: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)

# Keep the moving crawl locked to the finished 30-fps program clock even if an
# older environment file still contains a lower renderer cadence.
BASE.FPS = max(30, int(os.getenv("CRAWL_OVERLAY_FPS", "30")))
RENDER_SCALE = max(1, min(3, int(os.getenv("CRAWL_TEXT_RENDER_SCALE", "2"))))
_CACHE: dict[tuple[str, int, bool, int, int], tuple[Image.Image, int]] = {}
_CACHE_LOCK = threading.Lock()


def rich_line(text: str, size: int, bold: bool = True, emoji_size: int | None = None) -> tuple[Image.Image, int]:
    emoji_px = emoji_size or size + 3
    key = (text, size, bold, emoji_px, RENDER_SCALE)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

    scale = RENDER_SCALE
    high_font = BASE.font(size * scale, bold=bold)
    scratch = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    measure = ImageDraw.Draw(scratch)
    parts: list[tuple[str, str | Image.Image, int]] = []
    buffer = ""

    def high_text_width(value: str) -> int:
        if not value:
            return 0
        box = measure.textbbox((0, 0), value, font=high_font)
        return max(0, box[2] - box[0])

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        parts.append(("text", buffer, high_text_width(buffer)))
        buffer = ""

    for cluster in BASE.graphemes(text):
        icon = BASE.emoji_image(cluster, emoji_px * scale)
        if icon is None:
            buffer += cluster
        else:
            flush()
            parts.append(("emoji", icon, (emoji_px + 4) * scale))
    flush()

    high_width = max(1, sum(part[2] for part in parts))
    sample_box = measure.textbbox((0, 0), "Ag", font=high_font)
    text_height = sample_box[3] - sample_box[1]
    high_height = max((emoji_px + 8) * scale, text_height + 14 * scale)
    high = Image.new("RGBA", (high_width, high_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(high)
    x = 0
    text_y = (high_height - text_height) // 2 - sample_box[1]
    emoji_y = (high_height - emoji_px * scale) // 2
    for kind, payload, part_width in parts:
        if kind == "text":
            draw.text((x, text_y), str(payload), font=high_font, fill=BASE.WHITE)
        else:
            icon = payload
            assert isinstance(icon, Image.Image)
            high.paste(icon, (x + 2 * scale, emoji_y), icon)
        x += part_width

    final_width = max(1, (high_width + scale - 1) // scale)
    final_height = max(1, (high_height + scale - 1) // scale)
    line = high.resize((final_width, final_height), Image.Resampling.LANCZOS)
    result = (line, final_width)
    with _CACHE_LOCK:
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = result
    return result


class BoundarySequence:
    """Queue refreshed crawl payloads and swap them only at segment boundaries."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.messages: list[str] = []
        self.pending: list[str] | None = None
        self.current = ""
        self.index = 0
        self.started = time.monotonic()

    @staticmethod
    def incoming(value: dict[str, Any]) -> list[str]:
        if not value.get("active"):
            return []
        return [str(item) for item in value.get("messages", []) if str(item).strip()]

    def select(self, value: dict[str, Any], now: float) -> tuple[str, float]:
        incoming = self.incoming(value)
        with self.lock:
            if not self.current:
                if incoming:
                    self.messages = list(incoming)
                    self.pending = None
                    self.index = 0
                    self.current = self.messages[0]
                    self.started = now
                else:
                    self.messages = []
                    self.pending = None
                    self.index = 0
                    self.started = now
            elif incoming == self.messages:
                # Metadata-only API refreshes must never alter motion.
                self.pending = None
            elif incoming != self.pending:
                # Keep the segment already crossing the screen intact; retain only
                # the newest normalized payload for the next clean boundary.
                self.pending = list(incoming)
            return self.current, self.started

    def advance_if_complete(self, x: float, text_width_px: int, now: float) -> bool:
        with self.lock:
            if not self.current or x > -text_width_px:
                return False
            if self.pending is not None:
                self.messages = self.pending
                self.pending = None
                self.index = 0
                self.current = self.messages[0] if self.messages else ""
            elif self.messages:
                self.index = (self.index + 1) % len(self.messages)
                self.current = self.messages[self.index]
            else:
                self.current = ""
                self.index = 0
            self.started = now
            return True

    def pending_count(self) -> int:
        with self.lock:
            return len(self.pending or [])


# Base.frame() and Base.prime_emoji_cache() resolve these objects through their
# module globals, so these assignments upgrade the live crawl without forking
# the feed parser, layout engine, server, or animation clock.
BASE.rich_line = rich_line
BASE.SEQUENCE = BoundarySequence()

# Extend health with the motion contract so production certification can verify
# cadence and boundary swapping without inspecting visual content or restarting
# the renderer independently.
_original_do_get = BASE.Handler.do_GET


def do_get(self: Any) -> None:
    if self.path.startswith("/healthz"):
        value, error = BASE.STATE.snapshot()
        body = BASE.json.dumps(
            {
                "ok": True,
                "active": value["active"],
                "lastError": error,
                "emojiRenderer": "twemoji-png",
                "messageGraphemes": len(BASE.graphemes(str(value["message"]))),
                "messageCount": int(value.get("messageCount") or 0),
                "fps": BASE.FPS,
                "payloadSwap": "next-segment-boundary",
                "pendingCount": BASE.SEQUENCE.pending_count(),
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return
    _original_do_get(self)


BASE.Handler.do_GET = do_get


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()

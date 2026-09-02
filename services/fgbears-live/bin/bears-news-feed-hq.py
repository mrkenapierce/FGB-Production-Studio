#!/usr/bin/env python3
"""Deterministic 30-fps wrapper for the FGB Bears news ribbon.

The base renderer owns feed parsing, typography, caching and HTTP transport.
This wrapper changes only motion semantics: the current payload completes its
active scroll cycle before a refreshed payload is promoted, and the ribbon is
always rendered at the same 30-fps cadence as the finished program.
"""
from __future__ import annotations

import importlib.util
import math
import os
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

HERE = Path(__file__).resolve().parent
BASE_PATH = HERE / "bears-news-feed.py"
spec = importlib.util.spec_from_file_location("fgbears_bears_news_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load Bears news renderer: {BASE_PATH}")
BASE: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)

# A 15-fps moving source inside a 30-fps program necessarily repeats motion
# frames. Keep the ribbon clock locked to the program clock even if an older
# stream.env still contains BEARS_NEWS_OVERLAY_FPS=15.
BASE.FPS = max(30, int(os.getenv("BEARS_NEWS_OVERLAY_FPS", "30")))


class BoundaryState:
    """Hold refreshed RSS content until the next clean scroll-cycle boundary."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.message = ""
        self.pending: str | None = None
        self.pending_since: float | None = None
        self.started = time.monotonic()
        self.last_error: str | None = None

    def update(self, message: str) -> None:
        message = BASE.normalize(message)
        now = time.monotonic()
        publish_now: str | None = None
        with self.lock:
            if not self.message:
                self.message = message
                self.started = now
                self.pending = None
                self.pending_since = None
                publish_now = message
            elif message == self.message:
                # If a transient refresh briefly offered a different payload and
                # then returned to the current one, cancel that stale pending swap.
                self.pending = None
                self.pending_since = None
            elif message != self.pending:
                self.pending = message
                self.pending_since = now
            self.last_error = None
        if publish_now is not None:
            BASE.publish(publish_now)

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[str, float, str | None]:
        with self.lock:
            return self.message, self.started, self.last_error

    def promote_if_due(self, now: float, cycle_width: int) -> tuple[str, float, bool]:
        promoted = False
        promoted_message = ""
        with self.lock:
            if self.pending is not None and self.pending_since is not None and self.message:
                duration = max(0.001, float(cycle_width) / float(BASE.SCROLL_PPS))
                pending_elapsed = max(0.0, self.pending_since - self.started)
                next_cycle = math.floor(pending_elapsed / duration) + 1
                boundary = self.started + next_cycle * duration
                if now >= boundary:
                    self.message = self.pending
                    self.pending = None
                    self.pending_since = None
                    self.started = boundary
                    promoted = True
                    promoted_message = self.message
            message = self.message
            started = self.started
        if promoted:
            BASE.publish(promoted_message)
        return message, started, promoted

    def pending_chars(self) -> int:
        with self.lock:
            return len(self.pending or "")


STATE = BoundaryState()
BASE.STATE = STATE


def frame(now: float | None = None) -> Image.Image:
    if now is None:
        now = time.monotonic()
    message, started, _ = STATE.snapshot()
    if not message:
        return Image.new("RGBA", (BASE.WIDTH, BASE.HEIGHT), (0, 0, 0, 0))

    strip, cycle_width = BASE.ticker_cycle(message)
    message, started, promoted = STATE.promote_if_due(now, cycle_width)
    if promoted:
        strip, cycle_width = BASE.ticker_cycle(message)

    image = BASE.base_frame().copy()
    elapsed = max(0.0, now - started)
    offset = int((elapsed * BASE.SCROLL_PPS) % cycle_width)
    ticker = strip.crop((offset, 0, offset + BASE.VIEWPORT_WIDTH, BASE.VIEWPORT_HEIGHT))
    image.alpha_composite(ticker, (BASE.VIEWPORT_LEFT, BASE.VIEWPORT_TOP))
    return image


BASE.frame = frame

# Preserve the base HTTP/feed implementation but expose the new contract in
# health without creating another server or animation clock.
_original_do_get = BASE.Handler.do_GET


def do_get(self: Any) -> None:
    if self.path.startswith("/healthz"):
        message, _, error = STATE.snapshot()
        body = BASE.json.dumps(
            {
                "ok": True,
                "active": bool(message),
                "lastError": error,
                "renderer": "pillow-mjpeg-deterministic",
                "renderCache": "static-panel+precomposed-ticker",
                "messageChars": len(message),
                "pendingChars": STATE.pending_chars(),
                "payloadSwap": "next-cycle-boundary",
                "fps": BASE.FPS,
                "scrollPps": BASE.SCROLL_PPS,
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

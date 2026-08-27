#!/usr/bin/env python3
"""High-quality wrapper for the FGB lower-third crawl renderer.

The production program remains 1280x720. This wrapper keeps that exact canvas,
timing, feed, emoji and sequencing contract, but rasterizes crawl glyphs at 2x
(or CRAWL_TEXT_RENDER_SCALE) and downsamples with LANCZOS before composition.
That gives moving type a cleaner antialiased edge without changing crawl speed,
message order, dimensions, or the stable 30 fps transport.
"""
from __future__ import annotations

import importlib.util
import os
import threading
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


# Base.frame() and Base.prime_emoji_cache() resolve rich_line through their
# module globals, so this one assignment upgrades both normal and trivia crawls.
BASE.rich_line = rich_line


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()

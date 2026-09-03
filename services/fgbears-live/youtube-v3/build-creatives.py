#!/usr/bin/env python3
"""Build immutable local creatives for the YouTube v3 destination."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from PIL import Image

HERE = Path(__file__).resolve().parent
BUILDER = HERE.parent / "tools" / "build-youtube-rumble-trivia-card.py"
OUT = HERE / "creatives" / "yt_rumble_trivia_redirect.png"
WIDTH, HEIGHT = 798, 470
BACKGROUND = (11, 22, 42, 255)


def main() -> int:
    spec = importlib.util.spec_from_file_location("locked_redirect_builder", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load builder: {BUILDER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    source = module.build().convert("RGBA")
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (WIDTH, HEIGHT), BACKGROUND)
    out.alpha_composite(source, ((WIDTH - source.width) // 2, (HEIGHT - source.height) // 2))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, format="PNG", optimize=True)
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

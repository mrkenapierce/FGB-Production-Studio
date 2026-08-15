#!/usr/bin/env python3
"""Full-panel entry point for the FGBears advertising renderer.

Every uploaded image fills the complete 798x470 ad panel edge-to-edge without
stretching. Images are scaled proportionally until they cover the panel, then
only the excess outside the panel aspect ratio is center-cropped. There are no
letterbox bars, background extensions, or tiny centered images.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
BASE_RENDERER = HERE / "ad-overlay-base.py"
if not BASE_RENDERER.exists():
    # Source-tree/test fallback. Production install renames the original
    # renderer to ad-overlay-base.py before placing this wrapper at ad-overlay.py.
    BASE_RENDERER = HERE / "ad-overlay.py"

spec = importlib.util.spec_from_file_location("fgbears_ad_overlay_base", BASE_RENDERER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load base ad renderer: {BASE_RENDERER}")
BASE: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BASE)


def fit_image_to_panel(creative: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale proportionally and crop only the overflow to fill the panel."""
    target_w, target_h = size
    if target_w <= 0 or target_h <= 0:
        raise ValueError("panel dimensions must be positive")

    return ImageOps.fit(
        creative.convert("RGB"),
        (target_w, target_h),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def paste_image_fill(
    image: Image.Image,
    creative: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """Fill the entire renderer image box with an undistorted creative."""
    x1, y1, x2, y2 = box
    fitted = fit_image_to_panel(creative, (x2 - x1, y2 - y1))
    image.paste(fitted, (x1, y1))


# Replace the base renderer helper globally. Every existing image path—house
# cards, image-only ads, and mixed image creatives—now receives identical
# edge-to-edge cover behavior.
BASE.paste_image_fill = paste_image_fill


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()

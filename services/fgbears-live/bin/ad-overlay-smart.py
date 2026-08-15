#!/usr/bin/env python3
"""Aspect-safe entry point for the FGBears advertising renderer.

Keeps the complete uploaded image visible and undistorted inside the 798x470
ad panel. If an image has a different aspect ratio, only its outermost edge
pixels are extended into the unavoidable remainder so the panel still fills
edge-to-edge without cropping the source image or adding white/black bars.
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
    """Return a full-panel image with the complete source preserved.

    The source itself is only uniformly scaled. Any leftover width/height caused
    by a mismatched aspect ratio is filled by extending the nearest edge pixels.
    This guarantees no source cropping, no source stretching, and no letterbox
    bars while still returning exactly the requested panel dimensions.
    """
    target_w, target_h = size
    if target_w <= 0 or target_h <= 0:
        raise ValueError("panel dimensions must be positive")

    source = creative.convert("RGB")
    contained = ImageOps.contain(
        source,
        (target_w, target_h),
        method=Image.Resampling.LANCZOS,
    )
    if contained.size == (target_w, target_h):
        return contained

    fitted_w, fitted_h = contained.size
    left = (target_w - fitted_w) // 2
    top = (target_h - fitted_h) // 2
    right = target_w - fitted_w - left
    bottom = target_h - fitted_h - top

    # Start with a corner pixel so the canvas is always fully initialized,
    # including the theoretical case where integer rounding leaves both axes
    # one pixel short.
    corner = contained.getpixel((0, 0))
    canvas = Image.new("RGB", (target_w, target_h), corner)
    canvas.paste(contained, (left, top))

    if left:
        strip = contained.crop((0, 0, 1, fitted_h)).resize(
            (left, fitted_h), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (0, top))
    if right:
        strip = contained.crop((fitted_w - 1, 0, fitted_w, fitted_h)).resize(
            (right, fitted_h), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (left + fitted_w, top))
    if top:
        strip = contained.crop((0, 0, fitted_w, 1)).resize(
            (fitted_w, top), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (left, 0))
    if bottom:
        strip = contained.crop((0, fitted_h - 1, fitted_w, fitted_h)).resize(
            (fitted_w, bottom), Image.Resampling.NEAREST
        )
        canvas.paste(strip, (left, top + fitted_h))

    # Fill any corner rectangles created if both axes have residual space.
    if left and top:
        canvas.paste(Image.new("RGB", (left, top), contained.getpixel((0, 0))), (0, 0))
    if right and top:
        canvas.paste(
            Image.new("RGB", (right, top), contained.getpixel((fitted_w - 1, 0))),
            (left + fitted_w, 0),
        )
    if left and bottom:
        canvas.paste(
            Image.new("RGB", (left, bottom), contained.getpixel((0, fitted_h - 1))),
            (0, top + fitted_h),
        )
    if right and bottom:
        canvas.paste(
            Image.new("RGB", (right, bottom), contained.getpixel((fitted_w - 1, fitted_h - 1))),
            (left + fitted_w, top + fitted_h),
        )

    return canvas


def paste_image_fill(
    image: Image.Image,
    creative: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """Paste a complete, aspect-safe creative into any renderer image box."""
    x1, y1, x2, y2 = box
    target_w = x2 - x1
    target_h = y2 - y1
    fitted = fit_image_to_panel(creative, (target_w, target_h))
    image.paste(fitted, (x1, y1))


# Replace the base renderer's crop-to-fill helper globally. Every image path
# that already uses paste_image_fill (house cards, image-only ads, mixed ads)
# automatically receives the same aspect-safe behavior.
BASE.paste_image_fill = paste_image_fill


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()

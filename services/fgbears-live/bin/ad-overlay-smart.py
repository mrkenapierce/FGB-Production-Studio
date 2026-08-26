#!/usr/bin/env python3
"""Full-panel entry point for the FGBears advertising renderer.

Every uploaded image fills the complete 798x470 ad panel edge-to-edge without
stretching, a backing card, or a frame. Images are scaled proportionally until
they cover the panel, then only the excess outside the panel aspect ratio is
center-cropped. Transparent PNG/WebP pixels composite onto the Bears-blue live
screen instead of turning black or white. Any creative that contains an image
is treated as a full-panel image creative so it cannot fall back to the legacy
small mixed-image card layout.

The optional trivia presentation layer decorates this same renderer. It never
creates a second FFmpeg input or stream path; when inactive it is a no-op.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

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

# The base renderer historically emitted a fixed 25 fps MJPEG clock. Production
# FFmpeg now runs at 30 fps, and Oracle carries AD_OVERLAY_FPS alongside the
# FFmpeg input rate. Keep both sides on exactly the same clock so the full-screen
# ad/trivia input cannot throttle the entire program to 25/30 real-time speed.
BASE.FPS = max(1, int(os.getenv("AD_OVERLAY_FPS", "25")))


def fit_image_to_panel(creative: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale proportionally and crop only the overflow to fill the panel."""
    target_w, target_h = size
    if target_w <= 0 or target_h <= 0:
        raise ValueError("panel dimensions must be positive")

    mode = "RGBA" if "A" in creative.getbands() else "RGB"
    return ImageOps.fit(
        creative.convert(mode),
        (target_w, target_h),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def paste_image_fill(
    image: Image.Image,
    creative: Image.Image,
    box: tuple[int, int, int, int],
) -> None:
    """Blend an undistorted creative directly into the live screen."""
    x1, y1, x2, y2 = box
    if box == BASE.AD_PANEL_BOX:
        # Remove the white image backing and its visible margins. Text-only ads
        # retain that panel; photo ads blend into the Bears-blue broadcast.
        ImageDraw.Draw(image).rectangle(BASE.AD_PANEL_BACKGROUND_BOX, fill=BASE.BEARS_BLUE)
    fitted = fit_image_to_panel(creative, (x2 - x1, y2 - y1))
    if fitted.mode == "RGBA":
        image.paste(fitted, (x1, y1), fitted.getchannel("A"))
    else:
        image.paste(fitted, (x1, y1))


def image_creative_uses_full_panel(_sponsor: dict[str, Any]) -> bool:
    """Route every successfully loaded image through the 798x470 panel path."""
    return True


# Replace both legacy helpers globally. The base renderer only calls the image
# layout predicate after an image has loaded successfully, so returning True here
# means every photo uses AD_PANEL_BOX instead of the old 727x185 mixed-card box.
BASE.paste_image_fill = paste_image_fill
BASE.image_only_creative = image_creative_uses_full_panel

# Attach the game layer after the image-layout overrides so both advertisements
# and trivia share exactly the same permanent renderer and broadcast clock.
# Load it by absolute file path instead of relying on sys.path: the production
# launcher and the repository's runpy-based image-fit tests execute this wrapper
# differently, but both should resolve the same sibling module.
GAME_OVERLAY = HERE / "game_overlay.py"
game_spec = importlib.util.spec_from_file_location("fgbears_game_overlay", GAME_OVERLAY)
if game_spec is None or game_spec.loader is None:
    raise RuntimeError(f"Unable to load trivia game renderer: {GAME_OVERLAY}")
GAME_MODULE: Any = importlib.util.module_from_spec(game_spec)
game_spec.loader.exec_module(GAME_MODULE)
GAME_MODULE.install(BASE)


def main() -> None:
    BASE.main()


if __name__ == "__main__":
    main()

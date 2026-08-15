#!/usr/bin/env python3
from pathlib import Path
import runpy

from PIL import Image, ImageOps

root = Path(__file__).resolve().parents[1]
smart = runpy.run_path(str(root / "bin" / "ad-overlay-smart.py"))
fit_image_to_panel = smart["fit_image_to_panel"]

TARGET = (798, 470)

# Exact-ratio uploads must fill the panel pixel-for-pixel.
exact = Image.new("RGB", TARGET, (12, 34, 56))
exact.putpixel((0, 0), (255, 0, 0))
exact.putpixel((797, 469), (0, 255, 0))
exact_out = fit_image_to_panel(exact, TARGET)
assert exact_out.size == TARGET
assert exact_out.tobytes() == exact.tobytes()

# Extra-wide uploads must be proportionally enlarged and center-cropped so the
# complete 798x470 panel is occupied with no bars or stretching.
wide = Image.new("RGB", (1600, 400), (20, 40, 60))
for x in range(1600):
    wide.putpixel((x, 200), (x % 256, 50, 80))
wide_expected = ImageOps.fit(
    wide,
    TARGET,
    method=Image.Resampling.LANCZOS,
    centering=(0.5, 0.5),
)
wide_out = fit_image_to_panel(wide, TARGET)
assert wide_out.size == TARGET
assert wide_out.tobytes() == wide_expected.tobytes()

# Portrait uploads must also cover the entire panel; excess top/bottom content
# is center-cropped after proportional scaling rather than shrinking the image
# into a small centered card.
tall = Image.new("RGB", (400, 1200), (70, 90, 110))
for y in range(1200):
    tall.putpixel((200, y), (70, y % 256, 110))
tall_expected = ImageOps.fit(
    tall,
    TARGET,
    method=Image.Resampling.LANCZOS,
    centering=(0.5, 0.5),
)
tall_out = fit_image_to_panel(tall, TARGET)
assert tall_out.size == TARGET
assert tall_out.tobytes() == tall_expected.tobytes()

# Invalid panel geometry must fail rather than silently creating a broken frame.
try:
    fit_image_to_panel(exact, (0, 470))
except ValueError:
    pass
else:
    raise AssertionError("zero-width panel should fail")

source = (root / "bin" / "ad-overlay-smart.py").read_text(encoding="utf-8")
assert "ImageOps.fit(" in source
assert "ImageOps.contain(" not in source
assert "edge-to-edge" in source

install = (root / "bin" / "install.sh").read_text(encoding="utf-8")
assert "ad-overlay-base.py" in install
assert "ad-overlay-smart.py" in install
assert "ad-overlay.py" in install

print("Edge-to-edge ad image cover tests passed.")

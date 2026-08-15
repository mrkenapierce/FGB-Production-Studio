#!/usr/bin/env python3
from pathlib import Path
import runpy

from PIL import Image, ImageOps

root = Path(__file__).resolve().parents[1]
smart = runpy.run_path(str(root / "bin" / "ad-overlay-smart.py"))
fit_image_to_panel = smart["fit_image_to_panel"]

TARGET = (798, 470)

# Exact-ratio uploads must fill the panel pixel-for-pixel with no modification
# beyond RGB normalization.
exact = Image.new("RGB", TARGET, (12, 34, 56))
exact.putpixel((0, 0), (255, 0, 0))
exact.putpixel((797, 469), (0, 255, 0))
exact_out = fit_image_to_panel(exact, TARGET)
assert exact_out.size == TARGET
assert exact_out.tobytes() == exact.tobytes()

# A very wide photo must remain fully visible. The uniformly scaled source is
# preserved in the center and only its top/bottom edge pixels extend outward.
wide = Image.new("RGB", (1600, 400), (20, 40, 60))
wide.putpixel((0, 0), (255, 0, 0))
wide.putpixel((1599, 399), (0, 255, 0))
wide_contained = ImageOps.contain(wide, TARGET, method=Image.Resampling.LANCZOS)
wide_out = fit_image_to_panel(wide, TARGET)
assert wide_out.size == TARGET
wide_top = (TARGET[1] - wide_contained.height) // 2
assert wide_out.crop((0, wide_top, TARGET[0], wide_top + wide_contained.height)).tobytes() == wide_contained.tobytes()
assert wide_out.getbbox() == (0, 0, TARGET[0], TARGET[1])

# A portrait photo must also remain fully visible. The uniformly scaled source
# is preserved in the center and only its left/right edge pixels extend.
tall = Image.new("RGB", (400, 1200), (70, 90, 110))
tall.putpixel((0, 0), (255, 0, 0))
tall.putpixel((399, 1199), (0, 255, 0))
tall_contained = ImageOps.contain(tall, TARGET, method=Image.Resampling.LANCZOS)
tall_out = fit_image_to_panel(tall, TARGET)
assert tall_out.size == TARGET
tall_left = (TARGET[0] - tall_contained.width) // 2
assert tall_out.crop((tall_left, 0, tall_left + tall_contained.width, TARGET[1])).tobytes() == tall_contained.tobytes()
assert tall_out.getbbox() == (0, 0, TARGET[0], TARGET[1])

# Invalid panel geometry must fail rather than silently creating a broken frame.
try:
    fit_image_to_panel(exact, (0, 470))
except ValueError:
    pass
else:
    raise AssertionError("zero-width panel should fail")

install = (root / "bin" / "install.sh").read_text(encoding="utf-8")
assert "ad-overlay-base.py" in install
assert "ad-overlay-smart.py" in install
assert "ad-overlay.py" in install

print("Aspect-safe ad image sizing tests passed.")

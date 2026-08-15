#!/usr/bin/env python3
from pathlib import Path
import base64
import io
import runpy

from PIL import Image

root = Path(__file__).resolve().parents[1]
renderer = root / "bin" / "ad-overlay.py"
module = runpy.run_path(str(renderer))
rotation_slot = module["rotation_slot"]
image_only_creative = module["image_only_creative"]

assert module["HOUSE_INTERSTITIAL_SECONDS"] == 5
assert module["AD_PANEL_BOX"] == (462, 104, 1260, 574)

sponsors = [{"businessName": "A"}, {"businessName": "B"}]
assert rotation_slot(0.0, sponsors, interstitial_available=True, epoch=0.0) == (0, False)
assert rotation_slot(19.99, sponsors, interstitial_available=True, epoch=0.0) == (0, False)
assert rotation_slot(20.0, sponsors, interstitial_available=True, epoch=0.0) == (0, True)
assert rotation_slot(24.99, sponsors, interstitial_available=True, epoch=0.0) == (0, True)
assert rotation_slot(25.0, sponsors, interstitial_available=True, epoch=0.0) == (1, False)
assert rotation_slot(44.99, sponsors, interstitial_available=True, epoch=0.0) == (1, False)
assert rotation_slot(45.0, sponsors, interstitial_available=True, epoch=0.0) == (1, True)
assert rotation_slot(49.99, sponsors, interstitial_available=True, epoch=0.0) == (1, True)
assert rotation_slot(50.0, sponsors, interstitial_available=True, epoch=0.0) == (0, False)
# If the house asset is ever missing, rotation degrades safely instead of showing a broken slot.
assert rotation_slot(20.0, sponsors, interstitial_available=False, epoch=0.0) == (1, False)

assert image_only_creative({"imageUrl": "x", "fullScreen": True}) is True
assert image_only_creative({"imageUrl": "x", "layout": "full-bleed"}) is True
assert image_only_creative({"imageUrl": "x"}) is True
assert image_only_creative({"imageUrl": "x", "promoMessage": "Offer"}) is False

# Validate the exact source format used in production deployment. A successful
# Image.verify() is not enough for truncated JPEGs, so force a complete load.
asset_source = root / "assets" / "chicago-green-bay-comparison.base64.txt"
decoded = base64.b64decode(asset_source.read_text(encoding="ascii").strip(), validate=True)
chart = Image.open(io.BytesIO(decoded))
assert chart.format == "JPEG", chart.format
assert chart.size == (798, 470), chart.size
chart.load()

source = renderer.read_text(encoding="utf-8")
assert "ImageOps.fit(" in source, "image creatives must crop/fill instead of letterboxing"
assert 'canvas = Image.new("RGBA"' not in source, "image background canvas must be eliminated"
assert "def publish_frames()" in source, "five-second slots require frequent ad-frame publication"
assert "FRAME_PUBLISH_SECONDS" in source
assert "render_house_interstitial" in source

install = (root / "bin" / "install.sh").read_text(encoding="utf-8")
assert '"$SOURCE_DIR/assets/chicago-green-bay-comparison.base64.txt"' in install
assert "base64 --decode" in install
assert "/opt/fgbears-live/assets/chicago-green-bay-comparison.jpg" in install
assert "Image.open" in install and "im.load()" in install
assert '"$SOURCE_DIR/assets/chicago-green-bay-comparison.jpg"' not in install

print("Five-second house interstitial tests passed.")

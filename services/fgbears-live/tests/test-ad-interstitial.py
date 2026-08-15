#!/usr/bin/env python3
from pathlib import Path
import hashlib
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
assert rotation_slot(20.0, sponsors, interstitial_available=False, epoch=0.0) == (1, False)

assert image_only_creative({"imageUrl": "x", "fullScreen": True}) is True
assert image_only_creative({"imageUrl": "x", "layout": "full-bleed"}) is True
assert image_only_creative({"imageUrl": "x"}) is True
assert image_only_creative({"imageUrl": "x", "promoMessage": "Offer"}) is False

# Validate exactly what production will deploy. Full load is deliberately
# required: Image.verify() alone can accept a truncated JPEG scan.
asset = root / "assets" / "fgb-epic-default-interstitial.jpg"
decoded = asset.read_bytes()
assert hashlib.sha256(decoded).hexdigest() == "2e38173471f44dc3bf8fc8d09feea697d6bb77109ae812db9157e8e86a39bb51"
interstitial = Image.open(asset)
assert interstitial.format == "JPEG", interstitial.format
assert interstitial.size == (798, 470), interstitial.size
interstitial.load()

source = renderer.read_text(encoding="utf-8")
assert "ImageOps.fit(" in source, "image creatives must crop/fill instead of letterboxing"
assert 'canvas = Image.new("RGBA"' not in source, "image background canvas must be eliminated"
assert "def publish_frames()" in source, "five-second slots require frequent ad-frame publication"
assert "FRAME_PUBLISH_SECONDS" in source
assert "render_house_interstitial" in source

install = (root / "bin" / "install.sh").read_text(encoding="utf-8")
assert "fgb-epic-default-interstitial.jpg" in install
assert "install -m 0644" in install
assert "/opt/fgbears-live/assets/fgb-epic-default-interstitial.jpg" in install
assert "Image.open" in install and "im.load()" in install
assert 'im.size == (798, 470)' in install

print("Five-second house interstitial tests passed.")

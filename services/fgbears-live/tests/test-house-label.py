#!/usr/bin/env python3
from pathlib import Path
import runpy

root = Path(__file__).resolve().parents[1]
renderer = root / "bin" / "ad-overlay.py"
module = runpy.run_path(str(renderer))
show = module["show_advertisement_label"]

assert show("house") is False, "house posts must not display ADVERTISEMENT"
assert show("paid") is True, "paid sponsor posts must display ADVERTISEMENT"
assert show("placeholder") is True, "placeholder inventory keeps the advertising disclosure"

source = renderer.read_text(encoding="utf-8")
assert "if show_advertisement_label(kind):" in source
assert 'draw.text((505, 112), "ADVERTISEMENT"' in source

print("House-post advertisement-label tests passed.")

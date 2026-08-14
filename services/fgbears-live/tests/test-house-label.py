#!/usr/bin/env python3
from pathlib import Path
import runpy

root = Path(__file__).resolve().parents[1]
renderer = root / "bin" / "ad-overlay.py"
module = runpy.run_path(str(renderer))
show = module["show_advertisement_label"]
parts = module["sponsor_text_parts"]

assert show("house") is False, "house posts must not display ADVERTISEMENT"
assert show("paid") is True, "paid sponsor posts must display ADVERTISEMENT"
assert show("placeholder") is True, "placeholder inventory keeps the advertising disclosure"

# Legacy feed fallbacks can contain the word Advertisement as business/title
# copy. House creatives must strip that too, not merely hide the top label.
headline, subtitle, event_date = parts(
    {"businessName": "Advertisement", "title": "Advertisement", "subtitle": "Advertising"},
    "house",
)
assert headline == "", headline
assert subtitle == "", subtitle
assert event_date == "", event_date

source = renderer.read_text(encoding="utf-8")
assert "if show_advertisement_label(kind):" in source
assert 'draw.text((505, 112), "ADVERTISEMENT"' in source
assert 'fallback = "" if kind == "house" else "Advertisement"' in source

print("House-post advertisement-label tests passed.")

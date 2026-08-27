#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "game_overlay_policy.py"
spec = importlib.util.spec_from_file_location("fgb_policy_test", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeBase:
    ROTATION_SECONDS = 20
    ROTATION_EPOCH = 1000.0


m.BASE = FakeBase
m.LEGACY.BASE = FakeBase
sponsors = [
    {"businessName": "A", "durationSeconds": 7},
    {"businessName": "B", "durationMs": 13000},
]

# Explicitly passing interstitial_available=True must never insert a forced card.
assert m.rotation_slot(1000.0, sponsors, interstitial_available=True) == (0, False)
assert m.rotation_slot(1006.9, sponsors, interstitial_available=True) == (0, False)
assert m.rotation_slot(1007.0, sponsors, interstitial_available=True) == (1, False)
assert m.rotation_slot(1019.9, sponsors, interstitial_available=True) == (1, False)
assert m.rotation_slot(1020.0, sponsors, interstitial_available=True) == (0, False)

now = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc).timestamp()
assert m.ads_visible_now({"adsVisible": False}, now) is False
assert m.ads_visible_now({"adsVisible": True}, now) is True
assert m.ads_visible_now({"adsVisible": True, "adBreakEndsAt": "2026-08-27T18:00:01Z"}, now) is True
assert m.ads_visible_now({"adsVisible": True, "adBreakEndsAt": "2026-08-27T18:00:00Z"}, now) is False
assert m.ads_visible_now({}, now) is False

hq = (ROOT / "bin" / "crawl-overlay-hq.py").read_text(encoding="utf-8")
assert 'CRAWL_TEXT_RENDER_SCALE' in hq
assert 'Image.Resampling.LANCZOS' in hq

smart = (ROOT / "bin" / "ad-overlay-smart.py").read_text(encoding="utf-8")
assert 'game_overlay_policy.py' in smart

print("FGB broadcast policy tests passed.")

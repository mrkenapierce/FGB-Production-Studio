#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "game_overlay.py"
spec = importlib.util.spec_from_file_location("fgb_game_overlay_test", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeBase:
    ROTATION_SECONDS = 20
    HOUSE_INTERSTITIAL_SECONDS = 5
    ROTATION_EPOCH = 1000.0
    HOUSE_INTERSTITIAL_PATH = Path(tempfile.gettempdir()) / "fgb-no-house-interstitial.jpg"


m.BASE = FakeBase

# Per-ad timing from the existing sponsor feed is authoritative.
sponsors = [
    {"businessName": "A", "durationSeconds": 7},
    {"businessName": "B", "durationMs": 13000},
]
assert m.ad_duration_seconds(sponsors[0]) == 7
assert m.ad_duration_seconds(sponsors[1]) == 13
assert m.variable_rotation_slot(1000.0, sponsors, interstitial_available=False) == (0, False)
assert m.variable_rotation_slot(1006.9, sponsors, interstitial_available=False) == (0, False)
assert m.variable_rotation_slot(1007.0, sponsors, interstitial_available=False) == (1, False)
assert m.variable_rotation_slot(1019.9, sponsors, interstitial_available=False) == (1, False)
assert m.variable_rotation_slot(1020.0, sponsors, interstitial_available=False) == (0, False)

# Default alternate mode with one ad per break is GAME -> AD A -> GAME -> AD B.
game = {
    "visible": True,
    "adsEnabled": True,
    "presentationMode": "alternate_game_ads",
    "gameScreenSeconds": 20,
    "adsPerBreak": 1,
    "allowPaidAds": True,
    "allowHouseAds": False,
}
segments = m._presentation_segments(game, "paid", sponsors)
assert segments == [
    ("game", 20, None),
    ("ad", 7, 0),
    ("game", 20, None),
    ("ad", 13, 1),
], segments
assert m.presentation_slot(2000.0, game, "paid", sponsors, 2000.0)[:2] == ("game", None)
assert m.presentation_slot(2020.0, game, "paid", sponsors, 2000.0)[:2] == ("ad", 0)
assert m.presentation_slot(2027.0, game, "paid", sponsors, 2000.0)[:2] == ("game", None)
assert m.presentation_slot(2047.0, game, "paid", sponsors, 2000.0)[:2] == ("ad", 1)
assert m.presentation_slot(2060.0, game, "paid", sponsors, 2000.0)[:2] == ("game", None)

# Multiple ads per break group existing ads without inventing new ad inventory.
game["adsPerBreak"] = 2
assert m._presentation_segments(game, "paid", sponsors) == [
    ("game", 20, None),
    ("ad", 7, 0),
    ("ad", 13, 1),
]

# Disabling the eligible ad kind produces a continuous game screen.
game["allowPaidAds"] = False
assert m._presentation_segments(game, "paid", sponsors) == [("game", 20, None)]

# Crawl-only mode never asks the central renderer to replace the ad panel.
game["presentationMode"] = "crawl_only"
assert m._presentation_segments(game, "paid", sponsors) == [("game", 20, None)]

print("FGB trivia game overlay timing tests passed.")

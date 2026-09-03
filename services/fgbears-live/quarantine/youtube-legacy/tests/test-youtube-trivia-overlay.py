#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "youtube-trivia-overlay.py"
spec = importlib.util.spec_from_file_location("fgb_youtube_trivia_overlay_test", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

assert m.CARD_IMAGE.size == (1280, 720)
assert m.CARD_IMAGE.mode == "RGBA"
assert m.CARD_IMAGE.getpixel((640, 360))[3] == 255
assert len(m.TRANSPARENT_BYTES) == 1280 * 720 * 4

state = m.TriviaState()
state.update({"visible": True})
active, age, error = state.snapshot()
assert active is True
assert age < 1
assert error is None

state.update({"visible": False})
assert state.snapshot()[0] is False
state.update({"triviaActive": "yes"})
assert state.snapshot()[0] is True
state.last_good_refresh = time.time() - m.STALE_SECONDS - 1
assert state.snapshot()[0] is False

m.STATE.update({"visible": False})
assert m.frame_bytes() == m.TRANSPARENT_BYTES
m.STATE.update({"visible": True})
assert m.frame_bytes() == m.CARD_BYTES

print("YouTube-only Rumble trivia overlay tests passed.")

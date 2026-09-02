#!/usr/bin/env python3
"""Static regression guard for the supported YouTube exact-box renderer.

The production renderer obtains its live geometry from Lovable at startup, so
this integration test deliberately avoids importing it (which would perform a
network contract fetch). Instead it locks the architectural invariants that are
safe to verify offline. Live geometry and transport are certified separately by
the exact-card and production-audit workflows.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASK = ROOT / "bin" / "youtube-question-mask.py"
FULLSCREEN = ROOT / "bin" / "youtube-trivia-overlay.py"

assert MASK.is_file(), "supported exact-box renderer is missing"
assert not FULLSCREEN.exists(), "retired full-screen YouTube renderer was resurrected"

source = MASK.read_text(encoding="utf-8")

required = (
    "SOURCE_CANVAS_WIDTH = 1280",
    "SOURCE_CANVAS_HEIGHT = 720",
    "SOURCE_NEWS_BOTTOM = 104",
    "SOURCE_CRAWL_TOP = 574",
    'EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"',
    'youtube.get("rendersRealQuestion") is not False',
    'rumble.get("rendersRealQuestion") is not True',
    'youtube.get("presentationMode") != "full_creative_scaled"',
    "scaled maskRegion would overlap the always-live news or crawl bands",
    "Lovable presentation contract changed",
)
for marker in required:
    assert marker in source, f"missing exact-box invariant: {marker}"

for retired in (
    "full_middle_protection",
    "youtube-stream-router",
    "youtube-dynamic-card",
):
    assert retired not in source, f"retired YouTube architecture marker returned: {retired}"

print("YouTube exact-box renderer regression guards passed.")

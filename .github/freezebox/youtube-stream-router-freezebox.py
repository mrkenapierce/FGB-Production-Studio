#!/usr/bin/env python3
"""Hot-reload extension for the proven FGB YouTube emergency packet router.

The deployed emergency router is itself a thin patch layer. Importing it applies
its production audio-safe transport and question-routing overrides to the real
`youtube-stream-router.py` module exposed as `emergency.router`. This wrapper
then patches ONLY dynamic card reload behavior on that delegated StreamRouter.

If the emergency layer or delegated API is not present, startup fails before any
live cutover. The existing emergency service remains the rollback path.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

EMERGENCY_PATH = Path(
    os.getenv(
        "FGB_YOUTUBE_ROUTER_EMERGENCY_BASE",
        "/opt/fgbears-live/bin/youtube-stream-router-emergency.py",
    )
)

spec = importlib.util.spec_from_file_location("fgb_youtube_router_emergency", EMERGENCY_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load emergency router: {EMERGENCY_PATH}")
emergency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emergency)

router = getattr(emergency, "router", None)
if router is None:
    raise RuntimeError("emergency router did not expose delegated 'router' module")
for symbol in ("StreamRouter", "split_h264_access_units", "has_idr", "main"):
    if not hasattr(router, symbol):
        raise RuntimeError(f"delegated router missing required symbol: {symbol}")

StreamRouter = router.StreamRouter
for method in ("__init__", "_schedule_poll", "request_mode"):
    if not hasattr(StreamRouter, method):
        raise RuntimeError(f"delegated StreamRouter missing required method: {method}")

LOG = logging.getLogger("fgb-youtube-stream-router")
_orig_init = StreamRouter.__init__
_orig_schedule_poll = StreamRouter._schedule_poll
_orig_request_mode = StreamRouter.request_mode


def _patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
    _orig_init(self, *args, **kwargs)
    try:
        self._freezebox_card_mtime_ns = self.card_path.stat().st_mtime_ns
    except OSError:
        self._freezebox_card_mtime_ns = 0


def _maybe_reload_card(self: Any) -> None:
    """Atomically adopt a changed card only while the live path is selected.

    Invalid or half-written assets are ignored; the last known-good in-memory
    card remains active. The refresh script writes via rename, so a changed mtime
    represents a complete candidate asset.
    """
    if getattr(self, "_stopping", False):
        return
    if getattr(self, "current_mode", "live") != "live" or getattr(self, "pending_mode", None) == "card":
        return
    try:
        stat = self.card_path.stat()
        previous = getattr(self, "_freezebox_card_mtime_ns", 0)
        if stat.st_mtime_ns == previous:
            return
        blob = self.card_path.read_bytes()
        access_units = router.split_h264_access_units(blob)
        idr = [router.has_idr(au) for au in access_units]
        if not access_units or not any(idr):
            raise ValueError("candidate card has no usable IDR access unit")
        self.card_aus = access_units
        self.card_idr = idr
        self.card_index = 0
        self._freezebox_card_mtime_ns = stat.st_mtime_ns
        LOG.warning(
            "hot-reloaded freeze-box card: %d AUs, %d IDR, bytes=%d",
            len(access_units),
            sum(idr),
            len(blob),
        )
    except Exception as exc:
        LOG.error("freeze-box card reload rejected; keeping last known-good card: %s", exc)


def _patched_schedule_poll(self: Any):
    _maybe_reload_card(self)
    return _orig_schedule_poll(self)


def _patched_request_mode(self: Any, mode: str):
    if mode == "card":
        _maybe_reload_card(self)
    return _orig_request_mode(self, mode)


# Importing the emergency layer above has already applied its production
# audio-safe transport and desired-card policy to this same delegated class.
# These assignments preserve those patches and add only hot-reload behavior.
StreamRouter.__init__ = _patched_init
StreamRouter._maybe_reload_card = _maybe_reload_card
StreamRouter._schedule_poll = _patched_schedule_poll
StreamRouter.request_mode = _patched_request_mode

if __name__ == "__main__":
    raise SystemExit(router.main())

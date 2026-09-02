#!/usr/bin/env python3
"""Hot-reload extension for the proven FGB YouTube packet router.

The base emergency router remains untouched. This wrapper patches only card-asset
reload behavior so a freshly generated freeze-frame card can replace the old
full-screen emergency card between trivia rounds without restarting YouTube.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path

BASE_PATH = Path(os.getenv("FGB_YOUTUBE_ROUTER_BASE", "/opt/fgbears-live/bin/youtube-stream-router-emergency.py"))

spec = importlib.util.spec_from_file_location("fgb_youtube_router_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load base router: {BASE_PATH}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

LOG = logging.getLogger("fgb-youtube-stream-router")
_orig_init = base.StreamRouter.__init__
_orig_schedule_poll = base.StreamRouter._schedule_poll
_orig_request_mode = base.StreamRouter.request_mode


def _patched_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)
    try:
        self._freezebox_card_mtime_ns = self.card_path.stat().st_mtime_ns
    except OSError:
        self._freezebox_card_mtime_ns = 0


def _maybe_reload_card(self) -> None:
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
        access_units = base.split_h264_access_units(blob)
        idr = [base.has_idr(au) for au in access_units]
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


def _patched_schedule_poll(self):
    _maybe_reload_card(self)
    return _orig_schedule_poll(self)


def _patched_request_mode(self, mode: str):
    if mode == "card":
        _maybe_reload_card(self)
    return _orig_request_mode(self, mode)


base.StreamRouter.__init__ = _patched_init
base.StreamRouter._maybe_reload_card = _maybe_reload_card
base.StreamRouter._schedule_poll = _patched_schedule_poll
base.StreamRouter.request_mode = _patched_request_mode

if __name__ == "__main__":
    raise SystemExit(base.main())

#!/usr/bin/env python3
"""Production policy layer for FGB trivia/ad presentation.

This module sits on top of the legacy game overlay so Oracle follows the
server-authoritative trivia ad gate. Large ads are shown only while the public
game-screen feed explicitly reports adsVisible=true and the advertised break
has not expired. Outside that window the trivia game screen remains visible.

The legacy five-second FGB/EPIC interstitial is intentionally removed from
automatic sponsor rotation. House creative can still air when it arrives as
explicit house inventory from the sponsor feed.
"""
from __future__ import annotations

import importlib.util
import io
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE / "game_overlay.py"
spec = importlib.util.spec_from_file_location("fgbears_game_overlay_legacy", LEGACY_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load legacy trivia renderer: {LEGACY_PATH}")
LEGACY: Any = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LEGACY)

BASE: Any = None
_CACHE_LOCK = threading.Lock()
_CACHE_KEY: tuple[Any, ...] | None = None
_CACHE_BYTES = b""


def _parse_deadline(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def ads_visible_now(game: dict[str, Any], now: float | None = None) -> bool:
    """Fail closed: ads require an explicit live gate and a non-expired break."""
    current = time.time() if now is None else now
    if not LEGACY._truthy(game.get("adsVisible"), False):
        return False
    deadline = _parse_deadline(game.get("adBreakEndsAt"))
    if deadline is not None and current >= deadline:
        return False
    return True


def rotation_slot(
    now: float,
    sponsors: list[dict[str, Any]],
    interstitial_available: bool | None = None,
    epoch: float | None = None,
) -> tuple[int, bool]:
    """Rotate sponsor inventory by duration with no forced five-second card."""
    del interstitial_available
    if not sponsors:
        return 0, False
    start = BASE.ROTATION_EPOCH if epoch is None else epoch
    elapsed = max(0.0, now - start)
    durations = [LEGACY.ad_duration_seconds(sponsor) for sponsor in sponsors]
    total = sum(max(1, seconds) for seconds in durations)
    if total <= 0:
        return 0, False
    position = elapsed % total
    cursor = 0.0
    for index, seconds in enumerate(durations):
        cursor += max(1, seconds)
        if position < cursor:
            return index, False
    return len(sponsors) - 1, False


def _kind_allowed(game: dict[str, Any], kind: str) -> bool:
    if kind == "paid":
        return LEGACY._truthy(LEGACY._game_setting(game, "allowPaidAds", True), True)
    if kind == "house":
        return LEGACY._truthy(LEGACY._game_setting(game, "allowHouseAds", True), True)
    return bool(kind and kind not in {"suppressed", "placeholder"})


def current_frame(now: float | None = None):
    current = time.time() if now is None else now
    game, _refresh, _error, _revision, _epoch = LEGACY.GAME.snapshot()
    visible = LEGACY._truthy(game.get("visible"), False)

    if not visible:
        LEGACY._write_runtime("inactive", True)
        return LEGACY.ORIGINAL_CURRENT_FRAME(current)

    mode = str(LEGACY._game_setting(game, "presentationMode", "crawl_only") or "crawl_only")
    if mode != "alternate_game_ads":
        LEGACY._write_runtime("ad", True)
        return LEGACY.ORIGINAL_CURRENT_FRAME(current)

    # Server-authoritative gate: gameplay wins unless the API explicitly opens
    # a designated break. This removes stale/local timers as a source of ads.
    if not ads_visible_now(game, current):
        LEGACY._write_runtime("game", True)
        return LEGACY.render_game_screen(game, current)

    kind, _placeholder, sponsors, _sponsor_refresh, _sponsor_error, _sponsor_revision = BASE.STATE.snapshot()
    keep_crawl = LEGACY._truthy(LEGACY._game_setting(game, "keepTriviaCrawlDuringAds", True), True)

    # Fail closed at break start if inventory has not arrived yet: keep the
    # game screen rather than showing a placeholder or an unscheduled home card.
    if not sponsors or not _kind_allowed(game, kind):
        LEGACY._write_runtime("game", True)
        return LEGACY.render_game_screen(game, current)

    index, _ = rotation_slot(current, sponsors)
    LEGACY._write_runtime("ad", keep_crawl)
    return BASE.render_sponsor(sponsors[index])


def jpeg_bytes() -> bytes:
    global _CACHE_BYTES, _CACHE_KEY
    kind, _placeholder, sponsors, _refresh, _error, sponsor_revision = BASE.STATE.snapshot()
    game, _game_refresh, _game_error, game_revision, _epoch = LEGACY.GAME.snapshot()
    now = time.time()
    visible = LEGACY._truthy(game.get("visible"), False)
    mode = str(LEGACY._game_setting(game, "presentationMode", "crawl_only") or "crawl_only")
    gate = visible and mode == "alternate_game_ads" and ads_visible_now(game, now)

    if gate and sponsors and _kind_allowed(game, kind):
        index, _ = rotation_slot(now, sponsors)
        key = (sponsor_revision, game_revision, "ad", index)
    elif visible and mode == "alternate_game_ads":
        countdown = LEGACY._iso_countdown(game.get("phaseEndsAt"), now)
        key = (sponsor_revision, game_revision, "game", countdown)
    elif sponsors:
        index, _ = rotation_slot(now, sponsors)
        key = (sponsor_revision, -1, "normal", index)
    else:
        key = (sponsor_revision, -1, "placeholder", -1)

    with _CACHE_LOCK:
        if _CACHE_KEY == key and _CACHE_BYTES:
            return _CACHE_BYTES
        frame = current_frame(now)
        output = io.BytesIO()
        frame.save(output, format="JPEG", quality=94, subsampling=0, optimize=False)
        _CACHE_BYTES = output.getvalue()
        _CACHE_KEY = key
        return _CACHE_BYTES


def install(base: Any) -> None:
    """Install legacy feed/render helpers, then enforce current broadcast policy."""
    global BASE
    BASE = base
    LEGACY.install(base)

    # The sponsor endpoint intentionally returns `kind=suppressed` while trivia
    # gameplay owns the screen. Preserve the last good inventory in memory so a
    # short designated break can start immediately instead of waiting for the
    # slower sponsor poll to rediscover the same creatives.
    original_state_update = base.STATE.update

    def state_update(payload: dict[str, Any]) -> None:
        if str(payload.get("kind") or "").strip().lower() == "suppressed" and payload.get("suppressedBy") == "trivia":
            return
        original_state_update(payload)

    base.STATE.update = state_update

    # Remove the automatic five-second home/interstitial card everywhere. House
    # ads remain valid when they are explicit sponsor-feed inventory.
    base.rotation_slot = rotation_slot
    base.current_frame = current_frame
    base.jpeg_bytes = jpeg_bytes

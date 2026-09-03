#!/usr/bin/env python3
"""FGB YouTube router v5 control-plane wrapper.

Loads the proven packet router unchanged, but replaces its card-selection policy
with the authoritative Lovable `trivia.youtubeMaskActive` signal. Missing,
malformed, stale, or disabled state fails open to the normal live program.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

BASE = Path(__file__).with_name("youtube-stream-router-base.py")

spec = importlib.util.spec_from_file_location("fgb_youtube_stream_router_base", BASE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"unable to load base router: {BASE}")
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


def desired_card_v5(payload: dict[str, Any]) -> bool:
    """Use only the backend-authoritative question-safe mask flag.

    The control plane guarantees this is true only for a fresh, visible question
    phase with no ad creative and no ad break. Any uncertainty returns False.
    """
    try:
        if not bool((payload.get("platforms") or {}).get("youtube", True)):
            return False
        trivia = payload.get("trivia") or {}
        if bool(trivia.get("stale")):
            return False
        return trivia.get("youtubeMaskActive") is True
    except Exception:
        return False


router.desired_card = desired_card_v5

if __name__ == "__main__":
    try:
        raise SystemExit(router.main())
    except Exception as exc:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        router.LOG.exception("fatal router v5 error: %s", exc)
        raise SystemExit(70)

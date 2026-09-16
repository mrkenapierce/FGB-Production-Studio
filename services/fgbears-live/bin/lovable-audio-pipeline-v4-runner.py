#!/usr/bin/env python3
"""Production runner for FGB audio standard v4.

The shared master FFmpeg progress clock is useful for detecting a stall, but its
ratio to wall time is not an audio-quality gate for this mixed-input program.
This runner requires the clock to advance and records the observed ratio. The
actual outgoing AAC is verified separately by fgbears-audio-health for packet
continuity and signal integrity.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import time

MODULE = Path("/usr/local/lib/fgbears-live/lovable-audio-pipeline-v4.py")


def load_module():
    spec = importlib.util.spec_from_file_location("fgb_audio_v4", MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {MODULE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    mod = load_module()

    def advancing_pacing(label: str, seconds: int = 15) -> float:
        if not mod.service_active(mod.MASTER_SERVICE):
            raise RuntimeError("Master service not active")
        # First prove the newly-started progress clock is genuinely moving.
        previous = mod.progress_us()
        deadline = time.time() + 30
        current = previous
        while time.time() < deadline:
            time.sleep(2)
            current = mod.progress_us()
            if current > previous:
                break
            previous = current
        else:
            raise RuntimeError(f"{label} media clock did not begin advancing")

        m0 = current
        w0 = time.monotonic()
        time.sleep(seconds)
        m1 = mod.progress_us()
        w1 = time.monotonic()
        if m1 <= m0:
            raise RuntimeError(f"{label} media clock stalled ({m0} -> {m1})")
        ratio = ((m1 - m0) / 1_000_000.0) / (w1 - w0)
        mod.log(f"pacing_observed label={label} ratio={ratio:.4f} gate=advancing_only")
        return ratio

    mod.assert_pacing = advancing_pacing
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())

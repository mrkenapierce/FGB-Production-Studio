#!/usr/bin/env python3
"""Adapt the existing FGB transport health checker to audio standard v4.

The underlying checker still performs capture, decode, clipping, silence, channel,
DC and PTS checks. This wrapper changes only the expected transport sample rate
from the legacy 48 kHz assumption to the proven 44.1 kHz FGB standard.
"""
from __future__ import annotations

import re
import subprocess
import sys

BASE = "/opt/fgbears-live/bin/audio-health.py"
TARGET_RATE = "44100"
LEGACY_WARNING = "AUDIO_SAMPLE_RATE_NOT_48KHZ"
TARGET_WARNING = "AUDIO_SAMPLE_RATE_NOT_44_1KHZ"


def main() -> int:
    cp = subprocess.run(["python3", BASE, *sys.argv[1:]], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = cp.stdout or ""
    if "--self-test" in sys.argv[1:]:
        print(text, end="")
        return cp.returncode

    lines = text.splitlines()
    sample_rate = ""
    warnings: list[str] = []
    output: list[str] = []
    for line in lines:
        if line.startswith("audio_sample_rate="):
            sample_rate = line.split("=", 1)[1].strip()
        elif line.startswith("AUDIO_WARNINGS="):
            raw = line.split("=", 1)[1].strip()
            if raw and raw != "NONE":
                warnings.extend(x for x in raw.split(",") if x and x != LEGACY_WARNING)
            continue
        elif line.startswith("OVERALL_STATUS="):
            continue
        output.append(line)

    if sample_rate and sample_rate != TARGET_RATE and TARGET_WARNING not in warnings:
        warnings.append(TARGET_WARNING)
    # If capture failed before a sample rate could be read, preserve the base
    # failure via its REASON line / original return code.
    base_hard_failure = cp.returncode != 0 and not sample_rate
    status_fail = bool(warnings) or base_hard_failure
    output.append("AUDIO_WARNINGS=" + (",".join(warnings) if warnings else "NONE"))
    output.append("OVERALL_STATUS=" + ("FAIL" if status_fail else "OK"))
    print("\n".join(output) + "\n", end="")
    return 1 if status_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

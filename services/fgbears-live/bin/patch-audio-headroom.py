#!/usr/bin/env python3
"""One-shot repository patch for FGB live audio normalization and true-peak headroom."""
from pathlib import Path

OLD = "volume=-2dB,aresample=48000:first_pts=0"
NEW = "loudnorm=I=-14:LRA=11:TP=-1.5,aresample=48000:first_pts=0"


def replace_required(path_str: str) -> None:
    path = Path(path_str)
    text = path.read_text(encoding="utf-8")
    if OLD not in text:
        if NEW in text:
            print(f"already_updated={path_str}")
            return
        raise SystemExit(f"Expected audio-filter anchor missing in {path_str}")
    path.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print(f"updated={path_str}")


for target in (
    "services/fgbears-live/bin/start-stream.sh",
    "services/fgbears-live/bin/install.sh",
    "services/fgbears-live/config/stream.env.example",
):
    replace_required(target)

print("audio_true_peak_patch=OK")

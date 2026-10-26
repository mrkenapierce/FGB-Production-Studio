#!/usr/bin/env python3
"""Safely reclaim *only* redundant confirmed MP4 upload copies.

YouTube archival confirmation is created by archive-uploader.py only after
uploaded segment and playlist confirmation. Never delete original .ts, state
receipts, pending video, or open/young files. Dry-run is the default.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import stat
import time

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
STATE_ID = re.compile(r"^hourly-[A-Za-z0-9_-]+\.json$")
MP4_ID = re.compile(r"^[A-Za-z0-9_.+-]+\.mp4$")
MIN_AGE = 600


def candidates(root: Path, now: float) -> tuple[list[tuple[Path, Path, int]], dict[str, int]]:
    base = root.resolve(strict=True)
    state_dir = base / "state"
    final_dir = base / "final"
    counts = {"states": 0, "confirmed": 0, "pending": 0, "invalid": 0,
              "files": 0, "bytes": 0, "duplicates": 0}
    found: list[tuple[Path, Path, int]] = []
    seen: set[Path] = set()
    for state_file in sorted(state_dir.glob("hourly-*.json")):
        if not STATE_ID.fullmatch(state_file.name) or state_file.is_symlink():
            continue
        counts["states"] += 1
        try:
            record = json.loads(state_file.read_text())
        except (ValueError, OSError):
            counts["invalid"] += 1
            continue
        video_id = record.get("video_id")
        if record.get("confirmed") is not True or not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
            counts["pending"] += 1
            continue
        counts["confirmed"] += 1
        # Do not accept missing/implausibly future confirmation timestamps.
        confirmed_epoch = record.get("confirmed_epoch")
        if not isinstance(confirmed_epoch, (float, int)) or confirmed_epoch > now:
            counts["invalid"] += 1
            continue
        raw = record.get("mp4")
        if not isinstance(raw, str):
            continue
        source = Path(raw)
        # Each file is a remux final, not the raw MPEG-TS recording.
        # State produced in the container uses /archive/final/...
        if (not MP4_ID.fullmatch(source.name)
                or source.parent != Path("/archive/final")
                or source.name in (".", "..")):
            counts["invalid"] += 1
            continue
        target = final_dir / source.name
        if target in seen:
            counts["duplicates"] += 1
            continue
        seen.add(target)
        try:
            meta = target.lstat()
        except FileNotFoundError:
            continue
        if (not stat.S_ISREG(meta.st_mode)
                or meta.st_nlink != 1
                or meta.st_mtime > now - MIN_AGE
                or meta.st_size <= 0):
            continue
        # Also require 10-minute maturity since YouTube confirmation.
        if confirmed_epoch > now - MIN_AGE:
            continue
        # Strictly ensure no path traversal through symlinks or mounts.
        if target.resolve() != target or not target.resolve().is_relative_to(final_dir.resolve()):
            counts["invalid"] += 1
            continue
        counts["files"] += 1
        counts["bytes"] += meta.st_size
        found.append((state_file, target, meta.st_size))
    return found, counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/srv/fgb-archive")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-files", type=int, default=64)
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or not (root / "state").is_dir() or not (root / "final").is_dir():
        raise SystemExit("Unrecognized FGB archive directory")
    now = time.time()
    entries, counts = candidates(root, now)
    if args.max_files < 1 or args.max_files > 500:
        raise SystemExit("--max-files out of safety range")
    selected = entries[:args.max_files]
    deleted = 0
    reclaimed = 0
    if args.apply:
        # Defense-in-depth: evaluate each item again immediately before unlink.
        for receipt, target, expected in selected:
            fresh, _ = candidates(root, time.time())
            match = next(((a, b, n) for a, b, n in fresh
                          if a == receipt and b == target and n == expected), None)
            if not match:
                continue
            target.unlink()
            deleted += 1
            reclaimed += expected
    report = {"mode": "apply" if args.apply else "dry-run",
              "eligible": counts, "selectedFiles": len(selected),
              "selectedBytes": sum(x[2] for x in selected),
              "deletedFiles": deleted, "reclaimedBytes": reclaimed,
              "rawTransportFilesTouched": False, "receiptsTouched": False}
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

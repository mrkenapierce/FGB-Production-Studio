#!/usr/bin/env python3
"""CNT-only bounded, sanitized Chromium stderr sink. No network or credentials output."""
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location("watchdog", Path(__file__).with_name("capture-watchdog.py"))
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)
MAX_BYTES = 2_000_000


def sanitize(line, env):
    # Preserve the existing observer contract, but only its non-secret origin.
    origin = env.get("BROADCAST_ORIGIN", "").rstrip("/")
    marker = "EPIC_AIR_BOUNDARY " in line and origin and f"source: {origin}/" in line
    for key, value in env.items():
        if value and len(value) >= 4 and re.search(r"(?:KEY|SECRET|TOKEN|PASSWORD)$", key):
            line = line.replace(value, "[redacted]")
    line = wd.redact(line)
    if marker:
        line = re.sub(r"source: \[redacted\]", f"source: {origin}/", line)
    return line[:16_384]


def append(path, line, limit=MAX_BYTES):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("unsafe diagnostic path")
    data = line.encode("utf-8", "replace")[:16_384]
    if path.exists() and path.stat().st_size + len(data) > limit:
        backup = Path(str(path) + ".1")
        if backup.is_symlink():
            raise ValueError("unsafe diagnostic backup")
        os.replace(path, backup)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "ab") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(data + (b"" if data.endswith(b"\n") else b"\n"))


def main():
    os.umask(0o077)
    target = os.environ["CNT_CHROME_LOG"]
    # This collector is the sole writer, rotation remains safe while Chromium lives.
    while True:
        line = sys.stdin.readline(16_384)
        if not line:
            break
        append(target, sanitize(line, os.environ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
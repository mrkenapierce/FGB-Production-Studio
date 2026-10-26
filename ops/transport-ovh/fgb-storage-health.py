#!/usr/bin/env python3
"""Five-minute FGB-only free-space guard: safe MP4 cleanup + disk status.

Never changes FGB/CNT encoders, unpublished TS captures, databases or YouTube.
"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ARCHIVE = Path("/srv/fgb-archive")
STATE = Path("/var/lib/fgb-storage-health")
CLEANER = "/usr/local/libexec/fgb-confirmed-mp4-cleanup.py"


def run() -> None:
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("FGB_STORAGE_SKIP=already_running", flush=True)
            return
        before = shutil.disk_usage("/")
        free_gb = before.free / 1e9
        # Safe cleanup is always performed: the confirmed MP4 is a redundant
        # post-upload copy, while its TS original is subject to normal retention.
        proc = subprocess.run([sys.executable, CLEANER, "--root", str(ARCHIVE),
                               "--max-files", "128", "--apply"],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            print("FGB_STORAGE_CLEANUP_ERROR=" + proc.stderr[-400:], flush=True)
        try:
            cleanup = json.loads(proc.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            cleanup = {"error": "cleanup_did_not_return_json"}
        after = shutil.disk_usage("/")
        free_gb_after = round(after.free / 1e9, 3)
        severity = ("CRITICAL" if free_gb_after < 8 else
                    "WARNING" if free_gb_after < 15 else "OK")
        # The machine-readable state is accessible to the hourly GitHub check.
        report = {"checkedAt": int(time.time()), "severity": severity,
                  "freeGbBefore": round(free_gb, 3), "freeGb": free_gb_after,
                  "totalGb": round(after.total / 1e9, 3),
                  "thresholdWarningGb": 15, "thresholdCriticalGb": 8,
                  "cleanerExitCode": proc.returncode, "cleanup": cleanup,
                  "youtubeUnchanged": True, "cntUnchanged": True}
        temp = STATE / "status.json.new"
        temp.write_text(json.dumps(report, sort_keys=True) + "\n")
        os.chmod(temp, 0o600)
        temp.replace(STATE / "status.json")
        print("FGB_STORAGE_STATUS=" + json.dumps(report, sort_keys=True), flush=True)
        if severity != "OK" or proc.returncode != 0:
            raise SystemExit(2)


if __name__ == "__main__":
    run()

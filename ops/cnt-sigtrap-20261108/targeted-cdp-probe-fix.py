#!/usr/bin/env python3
"""CNT-only, reversible incident experiment. No encoder restart, no secrets."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

TARGET = Path("/opt/cnt/capture-watchdog.py")
BACKUP = Path("/cnt-state/watchdog/capture-watchdog.before-inspector-fix.py")
NEEDLE = '        s.sendall(_ws_frame(json.dumps({"id": 1, "method": "Inspector.enable"}).encode()))'
REPLACEMENT = '        # Avoid enabling Inspector on each 5-second probe; Runtime.evaluate still tests page.'


def fd_processes():
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        p = Path("/proc") / name
        try:
            if (p / "comm").read_text().strip() != "chromium":
                continue
            uid = (p / "status").read_text()
            fd = sum(1 for _ in (p / "fd").iterdir())
            soft, hard = resource.prlimit(int(name))
            found.append((int(name), fd, soft, hard))
        except (OSError, ValueError, PermissionError):
            continue
    return sorted(found, key=lambda v: -v[1])


def headroom():
    # Raise only the CNT renderer with 1024 soft FD ceiling, while keeping hard cap.
    # No broad host or FGB process changes; parent already has an 8192 soft limit.
    candidates = [x for x in fd_processes() if x[2] <= 1024 and x[3] >= 8192 and x[1] >= 200]
    if len(candidates) != 1:
        print("HEADROOM=SKIPPED_CANDIDATE_COUNT_" + str(len(candidates)), flush=True)
        return 0
    pid, count, soft, hard = candidates[0]
    try:
        resource.prlimit(pid, (8192, hard))
        newsoft, newhard = resource.prlimit(pid)
        if newsoft != 8192 or newhard != hard:
            raise RuntimeError("limit confirmation failed")
        print("HEADROOM=RAISED_TARGET_ONLY pid=" + str(pid) +
              " previous_soft=" + str(soft) + " new_soft=" + str(newsoft) +
              " open_fds=" + str(count), flush=True)
    except (OSError, PermissionError) as e:
        print("HEADROOM=UNAVAILABLE_" + type(e).__name__, flush=True)
        return 2
    return 0


def status_ok():
    try:
        v = json.loads(Path("/cnt-state/watchdog/status.json").read_text())
        return v.get("action") == "ok"
    except (OSError, ValueError):
        return False


def probe():
    spec = importlib.util.spec_from_file_location("cnt_watchdog_trial", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    reason, _detail = mod.probe(mod.cfg_for("cnt"))
    return reason


def fix():
    if not status_ok():
        raise RuntimeError("existing watchdog unhealthy; patch refused")
    if not TARGET.is_file() or not BACKUP.parent.is_dir():
        raise RuntimeError("production source or durable state volume missing")
    original = TARGET.read_text()
    if original.count(NEEDLE) != 1:
        raise RuntimeError("deployed code does not match exact guarded source")
    if BACKUP.exists():
        raise RuntimeError("existing persistent backup; refusing duplicate patch")
    count_before = fd_processes()
    selected = next((x for x in count_before if x[2] <= 1024 and x[1] >= 200), None)
    # Headroom might already have raised soft limit: choose most-FDs chromium process.
    if selected is None:
        selected = count_before[0] if count_before else None
    if not selected:
        raise RuntimeError("no chromium process exists")
    old_pid, old_count, _, _ = selected
    backup_tmp = BACKUP.with_suffix(".tmp")
    backup_tmp.write_text(original)
    os.chmod(backup_tmp, 0o600)
    os.replace(backup_tmp, BACKUP)
    tmp = TARGET.with_suffix(".trial.tmp")
    patched = original.replace(NEEDLE, REPLACEMENT, 1)
    tmp.write_text(patched)
    shutil.copymode(TARGET, tmp)
    os.replace(tmp, TARGET)
    print("CODE_PATCH=APPLIED_NO_RESTART", flush=True)
    try:
        subprocess.run([sys.executable, "-m", "py_compile", str(TARGET)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe() != "ok":
            raise RuntimeError("post-patch read-only browser probe was not healthy")
        # Compare FD growth over 60s against prior measured ~12 memfds/min.
        time.sleep(60)
        if probe() != "ok" or not status_ok():
            raise RuntimeError("post-patch browser health check failed")
        later = next((x for x in fd_processes() if x[0] == old_pid), None)
        if later is None:
            raise RuntimeError("renderer PID changed during trial")
        delta = later[1] - old_count
        print("FD_TRIAL_DELTA_OVER_60S=" + str(delta), flush=True)
        if delta > 8:
            raise RuntimeError("file descriptor growth still excessive")
        print("TRIAL=PASS_NO_STREAM_RESTART", flush=True)
        return 0
    except Exception as err:
        # Fail closed: restore exact prior script in the existing live CNT container.
        tmp = TARGET.with_suffix(".rollback.tmp")
        tmp.write_text(original)
        shutil.copymode(TARGET, tmp)
        os.replace(tmp, TARGET)
        print("TRIAL=ROLLBACK_" + type(err).__name__, flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("headroom", "fix"))
    args = parser.parse_args()
    try:
        return headroom() if args.action == "headroom" else fix()
    except Exception as e:
        print("TRIAL=BLOCKED_" + type(e).__name__, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

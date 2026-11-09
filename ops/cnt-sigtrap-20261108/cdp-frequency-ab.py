#!/usr/bin/env python3
"""CNT-only bounded A/B experiment: reduce DevTools cadence for 80 seconds, auto-restore."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

TARGET=Path("/opt/cnt/capture-watchdog.py")
BACKUP=Path("/cnt-state/watchdog/capture-watchdog.before-cdp-rate-trial.py")
NEEDLE="        reason, detail = probe_fn(c, process_exited)"
REPLACE="""        if channel == "cnt" and not process_exited and st.get("last_reason", "ok") == "ok" and now - st.get("cdp_rate_trial_last_at", 0) < 40:
            reason, detail = "ok", {"bounded_cdp_rate_test": True}
        else:
            reason, detail = probe_fn(c, process_exited)
            st["cdp_rate_trial_last_at"] = now"""
MARKER="bounded_cdp_rate_test"


def topfd():
    rows=[]
    for name in os.listdir("/proc"):
        if not name.isdigit(): continue
        p=Path("/proc")/name
        try:
            if (p/"comm").read_text().strip()!="chromium": continue
            count=sum(1 for _ in (p/"fd").iterdir())
            rows.append((int(name), count))
        except (OSError,ValueError): continue
    return max(rows,key=lambda x:x[1]) if rows else None


def healthy():
    try:
        st=json.loads(Path("/cnt-state/watchdog/status.json").read_text())
        return st.get("action")=="ok" and st.get("last_probe")
    except (OSError,ValueError):
        return False


def write_atomic(path, data, original_mode):
    tmp=path.with_suffix(".rate-trial.tmp")
    tmp.write_text(data)
    os.chmod(tmp,original_mode)
    os.replace(tmp,path)


def main():
    if not healthy():
        print("RATE_TRIAL=BLOCKED_WATCHDOG_UNHEALTHY",flush=True)
        return 1
    if not TARGET.is_file() or BACKUP.exists():
        print("RATE_TRIAL=BLOCKED_FILE_OR_BACKUP_CONFLICT",flush=True)
        return 1
    old=TARGET.read_text()
    if old.count(NEEDLE)!=1 or MARKER in old:
        print("RATE_TRIAL=BLOCKED_SOURCE_MISMATCH",flush=True)
        return 1
    selected=topfd()
    if not selected:
        print("RATE_TRIAL=BLOCKED_CHROMIUM_NOT_FOUND",flush=True)
        return 1
    pid, before=selected
    mode=TARGET.stat().st_mode & 0o777
    BACKUP.write_text(old)
    os.chmod(BACKUP,0o600)
    prior=old.replace(NEEDLE,REPLACE,1)
    patched=False
    def term_handler(_sig,_frame):
        raise KeyboardInterrupt("Interrupted trial")
    signal.signal(signal.SIGTERM,term_handler)
    signal.signal(signal.SIGINT,term_handler)
    try:
        write_atomic(TARGET,prior,mode)
        patched=True
        subprocess.run([sys.executable,"-m","py_compile",str(TARGET)],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print("RATE_TRIAL=ACTIVE_CDP_EVERY_40_SECONDS",flush=True)
        # The 5-second supervisor stays active and detects a dead browser process immediately.
        time.sleep(80)
        if not healthy(): raise RuntimeError("watchdog unhealthy")
        current=topfd()
        if not current or current[0]!=pid: raise RuntimeError("browser PID changed")
        delta=current[1]-before
        print("RATE_TRIAL_FD_DELTA_80S="+str(delta),flush=True)
        # Previous observed growth: 12 handles per 60 seconds; unchanged would be ~16.
        print("RATE_TRIAL_CONCLUSION="+("CDP_CORRELATED" if delta<=7 else "NO_PROVEN_CDP_CAUSALITY"),flush=True)
        return 0
    except BaseException as e:
        print("RATE_TRIAL=INCOMPLETE_"+type(e).__name__,flush=True)
        return 1
    finally:
        if patched and TARGET.is_file() and MARKER in TARGET.read_text():
            write_atomic(TARGET,old,mode)
            print("RATE_TRIAL_ORIGINAL_CODE_RESTORED=true",flush=True)


if __name__=="__main__":
    sys.exit(main())

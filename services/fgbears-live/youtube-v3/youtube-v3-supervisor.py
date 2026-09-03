#!/usr/bin/env python3
"""Single recovery authority for the FGB YouTube v3.6 branch.

Systemd does not restart the v3 media units. This supervisor restarts only the
v3 source/output when a process is dead or when media/transport advancement is
confirmed stalled or outside the live-edge budget. It never restarts the
shared master or Rumble.
"""
from __future__ import annotations

from datetime import datetime
import fcntl
from pathlib import Path
import re
import subprocess
import time

SOURCE = "fgbears-youtube-v3-source.service"
OUTPUT = "fgbears-youtube-v3.service"
MASTER = "fgbears-live.service"
RUMBLE = "fgbears-rumble-relay.service"
ROOT = Path("/run/fgbears-youtube-v3")
PLAYLIST = ROOT / "source/live.m3u8"
PROGRESS = ROOT / "output.progress"
START_FILE = ROOT / "output.start_epoch"
LOCK = ROOT / "recovery.lock"
INTERVAL = 5.0
HOLD_DOWN = 45.0
STARTUP_GRACE = 25.0
MAX_LAG_SECONDS = 8.0


def run(*args: str) -> str:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout.strip()


def active(unit: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def pid(unit: str) -> int:
    try:
        return int(run("systemctl", "show", "-p", "MainPID", "--value", unit) or "0")
    except ValueError:
        return 0


def age(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return 1e9


def latest_program_epoch() -> float:
    try:
        last = None
        for line in PLAYLIST.read_text(encoding="utf-8").splitlines():
            if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
                last = line.split(":", 1)[1].strip().replace("Z", "+00:00")
        return datetime.fromisoformat(last).timestamp() if last else 0.0
    except Exception:
        return 0.0


def source_ok() -> tuple[bool, str]:
    if not active(SOURCE):
        return False, "source_inactive"
    if age(PLAYLIST) > 7:
        return False, f"playlist_stale:{age(PLAYLIST):.1f}s"
    segments = list((ROOT / "source").glob("seg-*.ts"))
    if not segments:
        return False, "no_segments"
    newest = max(segments, key=lambda p: p.stat().st_mtime)
    if age(newest) > 7:
        return False, f"segment_stale:{age(newest):.1f}s"
    if latest_program_epoch() <= 0:
        return False, "program_time_missing"
    return True, "ok"


def progress_values() -> tuple[int, int, int]:
    vals: dict[str, str] = {}
    try:
        for line in PROGRESS.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k] = v
    except FileNotFoundError:
        return (0, 0, 0)
    def num(*keys: str) -> int:
        for k in keys:
            try:
                return int(float(vals.get(k, "0")))
            except ValueError:
                pass
        return 0
    return num("frame"), num("out_time_us", "out_time_ms"), num("total_size")


def output_lag(out_us: int) -> float:
    try:
        start = float(START_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 1e9
    live = latest_program_epoch()
    if live <= 0 or out_us <= 0:
        return 1e9
    # PDT marks the start of the newest ~2 second segment; add one segment to
    # approximate the current live edge. The target is ~one segment behind and
    # the hard operating budget is two segments plus small timing tolerance.
    return (live + 2.0) - (start + out_us / 1_000_000.0)


def tcp443(p: int) -> tuple[bool, int, int]:
    if p <= 0:
        return False, 0, 0
    text = run("ss", "-tinp", "state", "established")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if f"pid={p}," not in line or ":443" not in line:
            continue
        parts = line.split()
        sendq = 0
        if len(parts) >= 2:
            try:
                sendq = int(parts[1])
            except ValueError:
                pass
        detail = lines[i + 1] if i + 1 < len(lines) else ""
        m = re.search(r"bytes_acked:(\d+)", detail)
        acked = int(m.group(1)) if m else 0
        return True, acked, sendq
    return False, 0, 0


def restart_output(reason: str) -> None:
    print(f"V3_RECOVERY output reason={reason}", flush=True)
    subprocess.run(["systemctl", "restart", OUTPUT], check=False)


def restart_source(reason: str) -> None:
    print(f"V3_RECOVERY source reason={reason}", flush=True)
    subprocess.run(["systemctl", "restart", SOURCE], check=False)
    for _ in range(40):
        ok, _ = source_ok()
        if ok:
            break
        time.sleep(0.5)
    subprocess.run(["systemctl", "restart", OUTPUT], check=False)


def recover(kind: str, reason: str) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("V3_RECOVERY skipped=lock_busy", flush=True)
            return
        if kind == "source":
            restart_source(reason)
        else:
            restart_output(reason)


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    last_progress = (0, 0, 0)
    last_pid = 0
    last_acked = 0
    failures = {"source": 0, "output": 0}
    hold_until = time.monotonic() + STARTUP_GRACE

    while True:
        src_good, src_reason = source_ok()
        p = pid(OUTPUT)
        pr = progress_values()
        lag = output_lag(pr[1])
        connected, acked, sendq = tcp443(p)
        output_alive = active(OUTPUT) and p > 0

        if p != last_pid:
            last_pid = p
            last_acked = acked
            last_progress = pr
            hold_until = max(hold_until, time.monotonic() + STARTUP_GRACE)

        progress_advancing = pr[0] > last_progress[0] and pr[1] > last_progress[1]
        ack_advancing = connected and (last_acked == 0 or acked > last_acked)
        lag_ok = -2.0 <= lag <= MAX_LAG_SECONDS
        output_good = output_alive and connected and progress_advancing and ack_advancing and sendq < 2_000_000 and lag_ok

        if time.monotonic() < hold_until:
            failures = {"source": 0, "output": 0}
        else:
            failures["source"] = 0 if src_good else failures["source"] + 1
            failures["output"] = 0 if output_good else failures["output"] + 1

            if failures["source"] >= 2:
                recover("source", src_reason)
                failures = {"source": 0, "output": 0}
                hold_until = time.monotonic() + HOLD_DOWN
            elif failures["output"] >= 2:
                reason = f"alive={output_alive},connected={connected},progress={progress_advancing},ack={ack_advancing},sendq={sendq},lag={lag:.2f}"
                recover("output", reason)
                failures["output"] = 0
                hold_until = time.monotonic() + HOLD_DOWN

        print(
            f"V3_HEALTH source={src_good} output={output_good} pid={p} frame={pr[0]} "
            f"out_us={pr[1]} bytes={pr[2]} lag={lag:.2f}s connected={connected} acked={acked} sendq={sendq} "
            f"master={active(MASTER)} rumble={active(RUMBLE)}",
            flush=True,
        )
        last_progress = pr
        last_acked = acked
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())

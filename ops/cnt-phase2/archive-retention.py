#!/usr/bin/env python3
"""Host-local, channel-bound dependency journal and CNT retention. No network.

Only trusted publishers may call complete AFTER remote confirmation. Receipts
and pending windows are durable, never inferred from absence in an API list.
All manifest/hold writes and deletion share retention.lock (short critical sections).
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time


def root_path(value, channel):
    root = Path(value).resolve()
    if channel == "cnt" and (str(root).startswith("/srv/fgb-archive") or root == Path("/archive") or Path("/archive") in root.parents):
        raise ValueError("refusing FGB path")
    if channel == "fgb" and (str(root).startswith("/srv/cnt-archive") or root == Path("/cnt-archive") or Path("/cnt-archive") in root.parents):
        raise ValueError("refusing CNT path")
    return root


def atomic_json(path, value):
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with tmp.open("w") as handle:
        json.dump(value, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def epoch(path):
    match = re.fullmatch(r"live-(\d{8})-(\d{6})-([+-]\d{4})\.ts", path.name)
    if not match:
        return None
    import datetime
    return int(datetime.datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%z").timestamp())


def duration(path):
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=20, check=True)
        value = float(result.stdout.strip())
        return value if 0 < value < 86400 else None
    except (ValueError, subprocess.SubprocessError):
        return None


def decide(*, age, closed, holds_ok, held, dependencies, journal_ok=True):
    """One reason per concrete safety rule; age is measured from segment END."""
    if not closed:
        return False, "recording_now_or_unstable"
    if not holds_ok or not journal_ok:
        return False, "holds_or_journal_unavailable"
    pending = any(d.get("status") != "confirmed" for d in dependencies)
    if held or pending:
        return False, "OVERDUE_PENDING" if age > 10800 else "held_or_pending"
    if dependencies:
        if not all(d.get("videoId") and d.get("evidence") for d in dependencies):
            return False, "confirmation_incomplete"
        # Allow host observer/API discovery to catch up before early release.
        return (True, "published_all_dependencies") if age >= 180 else (False, "discovery_grace")
    return (True, "unneeded_three_hour_fallback") if age >= 10800 else (False, "within_three_hours")


def inventory(root, apply=False):
    state = root / "state"
    now = time.time()
    held = set()
    holds_ok = True
    for name in ("episode_hold", "daily_hold"):
        path = state / name
        try:
            if path.is_symlink() or not 0 <= now - path.stat().st_mtime < 600:
                raise ValueError("stale hold")
            held.update(path.read_text().splitlines())
        except (OSError, ValueError):
            holds_ok = False
            print(f"ALERT HOLD_STALE_OR_MISSING {name}; fail closed")
    deps = []
    # A capped/filtered episode_jobs response cannot certify that discovery is
    # exhaustive. Trusted host coordinator must supply this channel-bound lease
    # only after an exhaustive pending-window handshake (currently unsupported).
    journal_ok = (state / "dependencies").is_dir()
    try:
        lease_path = state / "discovery-ready.json"
        lease = json.loads(lease_path.read_text())
        journal_ok = journal_ok and not lease_path.is_symlink() and lease.get("channel") == "cnt" and lease.get("complete") is True and 0 <= now - lease["observedAt"] < 600
    except (OSError, ValueError, KeyError, TypeError):
        journal_ok = False
    if not journal_ok:
        print("ALERT DISCOVERY_UNAVAILABLE; exhaustive dependency handshake required; fail closed")
    for path in (state / "dependencies").glob("*.json"):
        try:
            row = json.loads(path.read_text())
            if path.is_symlink() or row["channel"] != "cnt" or not isinstance(row["start"], int) or not isinstance(row["end"], int) or row["end"] <= row["start"]:
                raise ValueError("bad dependency")
            deps.append(row)
        except (OSError, ValueError, KeyError, TypeError):
            journal_ok = False
    files = list((root / "rolling").glob("live-*.ts"))
    parsed = [(epoch(p), p) for p in files]
    newest = max((s for s, _ in parsed if s is not None), default=None)
    total = eligible = overdue = 0
    for start, path in sorted(parsed, key=lambda pair: pair[0] or 0):
        if path.is_symlink() or not path.is_file() or start is None:
            print(f"KEEP {path.name} invalid_or_symlink")
            continue
        stat = path.stat()
        total += stat.st_size
        closed = start != newest and now - stat.st_mtime >= 30
        length = duration(path) if closed else None
        if length is None:
            print(f"KEEP {path.name} recording_now_or_unreadable")
            continue
        end = start + length
        matching = [d for d in deps if d["start"] < end and d["end"] > start]
        safe, why = decide(age=now-end, closed=closed, holds_ok=holds_ok, held=path.name in held, dependencies=matching, journal_ok=journal_ok)
        if why == "OVERDUE_PENDING":
            overdue += stat.st_size
            print(f"ALERT OVERDUE_PENDING {path.name}; upload/backup required, not deleted")
        print(f"{'ELIGIBLE' if safe else 'KEEP'} {path.name} {stat.st_size} {why}")
        if safe:
            eligible += stat.st_size
            # Recheck identity/size/mtime under the same shared producer lock.
            if apply and path.stat() == stat and not path.is_symlink():
                path.unlink()
                print(f"DELETED {path.name}")
    print(f"SUMMARY mode={'apply' if apply else 'dry-run'} total_bytes={total} eligible_bytes={eligible} overdue_bytes={overdue}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["register", "complete", "inventory"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--channel", choices=["fgb", "cnt"], required=True)
    parser.add_argument("--kind", choices=["episode", "daily"])
    parser.add_argument("--id")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--video")
    parser.add_argument("--evidence", choices=["cnt_cleanup_confirmed", "episode_processing_confirmed"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = root_path(args.root, args.channel)
    state = root / "state"
    if args.action == "inventory":
        if args.channel != "cnt":
            parser.error("FGB deletion belongs to external production uploader")
        # Inventory must not create state or receipts.
        if not (state / "retention.lock").is_file():
            print("ALERT retention.lock missing; fail closed (initialize publishers first)")
            return
    else:
        state.mkdir(parents=True, exist_ok=True)
    if (state / "retention.lock").is_symlink():
        parser.error("refusing symlink lock")
    with (state / "retention.lock").open("r+" if args.action == "inventory" else "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "inventory":
            inventory(root, args.apply and os.environ.get("CNT_RETENTION_APPLY") == "yes")
            return
        if not args.kind or not args.id or not re.fullmatch(r"[a-zA-Z0-9_+\-]{1,80}", args.id):
            parser.error("safe kind/id required")
        directory = state / "dependencies"
        if directory.is_symlink():
            parser.error("refusing symlink dependency directory")
        directory.mkdir(exist_ok=True)
        path = directory / f"{args.kind}-{args.id}.json"
        if path.is_symlink():
            parser.error("refusing symlink receipt")
        row = json.loads(path.read_text()) if path.exists() else None
        if args.action == "register":
            if args.start is None or args.end is None or args.end <= args.start:
                parser.error("valid window required")
            if row and (row["start"] != args.start or row["end"] != args.end or row["channel"] != args.channel):
                parser.error("immutable dependency window/channel mismatch")
            if not row:
                atomic_json(path, {"channel": args.channel, "kind": args.kind, "id": args.id, "start": args.start, "end": args.end, "status": "pending"})
        else:
            if not row or not args.video or not re.fullmatch(r"[a-zA-Z0-9_-]{11}", args.video) or not args.evidence:
                parser.error("existing dependency and verified video/evidence required")
            if args.kind == "daily" and (args.channel != "cnt" or args.evidence != "cnt_cleanup_confirmed"):
                parser.error("daily confirmation must be CNT cleanup membership")
            if args.kind == "episode" and args.evidence != "episode_processing_confirmed":
                parser.error("episode processing confirmation required")
            if row.get("videoId") and row["videoId"] != args.video:
                parser.error("immutable video mismatch")
            atomic_json(path, {**row, "status": "confirmed", "videoId": args.video, "evidence": args.evidence, "confirmedAt": int(time.time())})


if __name__ == "__main__":
    main()
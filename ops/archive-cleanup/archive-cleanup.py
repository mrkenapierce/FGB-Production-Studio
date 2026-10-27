#!/usr/bin/env python3
"""Receipt-gated three-hour archive cleanup for ONE channel (fgb | cnt).

SAFE DEFAULTS: DRY_RUN=true. Real deletion additionally requires
CLEANUP_CONFIRM_DELETE=yes. Nothing else in this file can remove a file.

A file is DELETABLE only when ALL of these hold:
  * it sits directly in the channel's scan directory, is a regular file (not a
    symlink), and matches live-%Y%m%d-%H%M%S-%z.ts (e.g. live-20261027-120001--0500.ts);
  * it is closed: not the newest file, and unmodified for CLOSED_GRACE_SECONDS;
  * the app's signed `cleanup` action (the existing approved archive endpoint)
    lists its segment id in confirmedSegmentIds, i.e. BOTH the YouTube upload
    and the playlist insert are confirmed for this channel;
  * it is not listed in a hold file, and every hold file is fresh (fail closed).
  * it is at least RETENTION_HOURS old, measured from its last write (close);
    confirmed files younger than that are PROTECTED as within_retention.
Everything else is PROTECTED indefinitely; protected footage older than
RETENTION_HOURS raises an OVERDUE alert and is still never deleted.
If the endpoint is unreachable, refuses, or returns a malformed receipt list,
the run deletes nothing.

Status for monitoring: <state>/cleanup-status.json (last_run, mode,
candidate_count, deleted_count, protected_count, overdue_count, disk_free_mb,
error). Stdlib only; no shell, no network other than the configured endpoint.
"""
import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request

NAME_RE = re.compile(r"live-(\d{8})-(\d{6})-([+-]\d{4})\.ts")
SEGMENT_RE = re.compile(r"\d{8}T\d{6}[+-]\d{4}")

CHANNELS = {
    "fgb": {
        "root": "/srv/fgb-archive", "scan": "hourly", "url_env": "ARCHIVE_URL",
        # Static key preferred when configured; HMAC heartbeat secret otherwise.
        "key_env": "FGB_ARCHIVE_API_KEY", "hmac_env": "FGB_TRANSPORT_HEARTBEAT_SECRET", "prefix": "x-fgb",
        "forbidden": ("/srv/cnt-archive", "/cnt-archive"),
    },
    "cnt": {
        "root": "/cnt-archive", "scan": "rolling", "url_env": "CNT_ARCHIVE_URL",
        # CNT production contract: static archive key only (existing env name).
        "key_env": "CNT_ARCHIVE_HMAC_SECRET", "hmac_env": None, "prefix": "x-cnt",
        "forbidden": ("/srv/fgb-archive", "/archive"),
    },
}


def truthy(value, default):
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def segment_id(name):
    """live-20261027-120001--0500.ts -> 20261027T120001-0500 (app segment id)."""
    m = NAME_RE.fullmatch(name)
    return f"{m.group(1)}T{m.group(2)}{m.group(3)}" if m else None


def start_epoch(name):
    m = NAME_RE.fullmatch(name)
    if not m:
        return None
    try:
        return int(datetime.datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S%z").timestamp())
    except ValueError:
        return None


def check_root(channel, root):
    cfg = CHANNELS[channel]
    resolved = Path(root).resolve()
    for bad in cfg["forbidden"]:
        if resolved == Path(bad) or Path(bad) in resolved.parents:
            raise SystemExit(f"refusing {resolved}: belongs to the other channel")
    return resolved


def auth_headers(channel, env, body):
    """Exactly one auth method per request; never reuses one value for both.
    Raises RuntimeError (fail closed) when the channel's credential is missing."""
    cfg = CHANNELS[channel]
    prefix, key = cfg["prefix"], env.get(cfg["key_env"]) or ""
    if key:
        return {f"{prefix}-archive-key": key}
    secret = env.get(cfg["hmac_env"]) if cfg["hmac_env"] else ""
    if not secret:
        needed = cfg["key_env"] + (f" or {cfg['hmac_env']}" if cfg["hmac_env"] else "")
        raise RuntimeError(f"{needed} not set")
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return {f"{prefix}-timestamp": ts, f"{prefix}-signature": sig}


def signed_post(url, channel, env, body, timeout=30):
    headers = {"content-type": "application/json", **auth_headers(channel, env, body)}
    req = urllib.request.Request(url, data=body.encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed configured URL)
        return json.loads(resp.read(2_000_000))


def fetch_receipts(fetch):
    """Returns a set of confirmed ids, or raises. Malformed => raise (delete nothing)."""
    data = fetch(json.dumps({"action": "cleanup"}, separators=(",", ":")))
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError("endpoint refused cleanup receipts")
    ids = data.get("confirmedSegmentIds")
    if not isinstance(ids, list) or not all(isinstance(i, str) and SEGMENT_RE.fullmatch(i) for i in ids):
        raise RuntimeError("malformed receipt list")
    return set(ids)


def read_holds(state, names, now, max_age):
    """Returns (held_names, ok). A missing or stale required hold fails closed."""
    held, ok = set(), True
    for name in names:
        path = state / name
        try:
            if path.is_symlink() or not 0 <= now - path.stat().st_mtime < max_age:
                raise ValueError("stale")
            held.update(line.strip() for line in path.read_text().splitlines() if line.strip())
        except (OSError, ValueError):
            ok = False
    return held, ok


def classify(files, *, now, receipts, held, holds_ok, grace, retention):
    """Pure decision: list of (name, action, reason, size). action in DELETE/PROTECT."""
    out = []
    starts = [s for s in (start_epoch(f["name"]) for f in files if f["kind"] == "file") if s is not None]
    newest = max(starts, default=None)
    for f in sorted(files, key=lambda x: x["name"]):
        name, size = f["name"], f.get("size", 0)
        if f["kind"] == "symlink":
            out.append((name, "PROTECT", "symlink", 0)); continue
        if f["kind"] == "dir":
            out.append((name, "PROTECT", "unexpected_directory", 0)); continue
        if f["kind"] != "file":
            out.append((name, "PROTECT", "not_regular_file", 0)); continue
        start, sid = start_epoch(name), segment_id(name)
        if start is None or sid is None:
            out.append((name, "PROTECT", "unexpected_name", size)); continue
        age = now - start
        if start == newest or now - f["mtime"] < grace:
            out.append((name, "PROTECT", "active_write", size)); continue
        if not holds_ok:
            out.append((name, "PROTECT", "holds_unavailable", size)); continue
        if name in held or sid in held:
            out.append((name, "PROTECT", "OVERDUE_held" if age > retention else "held", size)); continue
        if receipts is None:
            out.append((name, "PROTECT", "receipts_unavailable", size)); continue
        if sid in receipts:
            # Strict minimum: age since the file was last written (its close).
            if now - f["mtime"] < retention:
                out.append((name, "PROTECT", "confirmed_within_retention", size)); continue
            out.append((name, "DELETE", "publish_confirmed_past_retention", size)); continue
        out.append((name, "PROTECT", "OVERDUE_unpublished" if age > retention else "unpublished_within_retention", size))
    return out


def scan(directory):
    files = []
    for entry in os.scandir(directory):
        if entry.is_symlink():
            files.append({"name": entry.name, "kind": "symlink"})
        elif entry.is_dir(follow_symlinks=False):
            files.append({"name": entry.name, "kind": "dir"})
        elif entry.is_file(follow_symlinks=False):
            st = entry.stat(follow_symlinks=False)
            files.append({"name": entry.name, "kind": "file", "size": st.st_size, "mtime": st.st_mtime,
                          "ino": st.st_ino, "dev": st.st_dev})
        else:
            files.append({"name": entry.name, "kind": "other"})
    return files


def run(channel, env=os.environ, fetch=None, now=None):
    cfg = CHANNELS[channel]
    root = check_root(channel, env.get("CLEANUP_ROOT") or cfg["root"])
    directory = root / cfg["scan"]
    state = root / "state"
    dry = truthy(env.get("DRY_RUN"), True) or env.get("CLEANUP_CONFIRM_DELETE") != "yes"
    retention = float(env.get("RETENTION_HOURS") or 3) * 3600
    grace = int(env.get("CLOSED_GRACE_SECONDS") or 120)
    holds = [h for h in (env.get("CLEANUP_HOLD_FILES", "episode_hold daily_hold")).split() if h]
    require_holds = truthy(env.get("CLEANUP_REQUIRE_HOLDS"), True)
    if not directory.is_dir() or directory.is_symlink():
        raise SystemExit(f"scan directory missing or symlink: {directory}")
    if not state.is_dir() or state.is_symlink():
        raise SystemExit(f"state directory missing or symlink: {state}")
    lock_path = state / "cleanup.lock"
    if lock_path.is_symlink():
        raise SystemExit("refusing symlink lock")
    status = {"channel": channel, "last_run": None, "mode": "dry-run" if dry else "apply",
              "retention_hours": retention / 3600, "candidate_count": 0, "deleted_count": 0,
              "protected_count": 0, "overdue_count": 0, "deleted_bytes": 0, "disk_free_mb": None, "error": None}
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("SKIP another cleanup run holds the lock")
            return 0
        now = time.time() if now is None else now
        receipts = None
        try:
            if fetch is None:
                url = env.get(cfg["url_env"])
                if not url:
                    raise RuntimeError(f"{cfg['url_env']} not set")
                auth_headers(channel, env, "{}")  # fail closed before any request
                fetch = lambda body: signed_post(url, channel, env, body)  # noqa: E731
            receipts = fetch_receipts(fetch)
        except Exception as exc:  # any failure => delete nothing
            status["error"] = f"receipts: {str(exc)[:200]}"
            print(f"ALERT RECEIPTS_UNAVAILABLE {status['error']}; deleting nothing")
        if require_holds:
            held, holds_ok = read_holds(state, holds, now, 600)
        else:
            held, holds_ok = read_holds(state, [h for h in holds if (state / h).exists()], now, 600)
        if not holds_ok:
            print("ALERT HOLDS_STALE_OR_MISSING; deleting nothing")
        files = scan(directory)
        by_name = {f["name"]: f for f in files}
        for name, action, reason, size in classify(files, now=now, receipts=receipts, held=held,
                                                   holds_ok=holds_ok, grace=grace, retention=retention):
            if reason.startswith("OVERDUE"):
                status["overdue_count"] += 1
                print(f"ALERT {reason} {name}; kept, needs upload or backup")
            if action == "PROTECT":
                status["protected_count"] += 1
                print(f"PROTECT {name} {reason}")
                continue
            status["candidate_count"] += 1
            if dry:
                print(f"WOULD_DELETE {name} {size} {reason}")
                continue
            path, before = directory / name, by_name[name]
            try:
                st = os.lstat(path)
                if (not os.path.isfile(path) or os.path.islink(path) or st.st_ino != before["ino"]
                        or st.st_dev != before["dev"] or st.st_size != before["size"] or st.st_mtime != before["mtime"]):
                    print(f"PROTECT {name} changed_since_scan"); status["protected_count"] += 1; continue
                path.unlink()
                status["deleted_count"] += 1
                status["deleted_bytes"] += size
                print(f"DELETED {name} {size}")
            except OSError as exc:
                print(f"PROTECT {name} unlink_failed {exc.errno}"); status["protected_count"] += 1
        status["disk_free_mb"] = int(shutil.disk_usage(directory).free / 1048576)
        status["last_run"] = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat()
        tmp = state / f"cleanup-status.json.tmp.{os.getpid()}"
        tmp.write_text(json.dumps(status))
        os.replace(tmp, state / "cleanup-status.json")
        print("SUMMARY " + " ".join(f"{k}={v}" for k, v in status.items() if k != "error"))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CHANNELS:
        raise SystemExit("usage: archive-cleanup.py fgb|cnt")
    sys.exit(run(sys.argv[1]))

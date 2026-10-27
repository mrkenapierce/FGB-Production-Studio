#!/usr/bin/env python3
"""One-time FGB source reclamation. Fails closed on publication/dependency uncertainty.
Requires --apply; otherwise performs a non-destructive dry run. Run inside archive
uploader container: credentials remain in process environment, never in logs.
Existing live encoder and uploader process are not restarted or modified.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import time

SOURCE=re.compile(r"^live-(\d{8})-(\d{6})-([+-]\d{4})\.ts$")
VIDEO=re.compile(r"^[A-Za-z0-9_-]{11}$")
ROOT=Path("/archive")
CHANNEL="UC3qyMq_KCg7aF08x7LZyVtg"
MIN_FINISH_AGE=3*3600
MIN_FILE_IDLE=600
MAX_COUNT=25
AUTH_PATH="/opt/transport/archive-uploader.py"

def fail(reason: str):
    raise SystemExit("FGB_RECLAIM_ABORTED: "+reason)

def start_epoch(name: str):
    match=SOURCE.fullmatch(name)
    if not match:
        return None
    try:
        return dt.datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%z").timestamp()
    except ValueError:
        return None

def deps(api):
    """Fresh exhaustive snapshot of all unposted episode source intervals."""
    cursor=None
    windows=[]
    initial_snapshot=None
    loops=0
    while True:
        req={"action":"episode_jobs","pageSize":100}
        if cursor:
            req["cursor"]=cursor
        response=api(req)
        if response.get("ok") is not True:
            fail("episode_registry_unavailable")
        page=response.get("dependencies")
        if not isinstance(page,dict) or type(page.get("complete")) is not bool:
            fail("episode_registry_shape_invalid")
        snapshot=page.get("snapshotAt")
        try:
            age=abs((dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(snapshot.replace("Z","+00:00"))).total_seconds())
        except (AttributeError, ValueError, TypeError):
            fail("dependency_snapshot_time_invalid")
        if age>120:
            fail("dependency_snapshot_stale")
        if initial_snapshot is None:
            initial_snapshot=snapshot
        if snapshot!=initial_snapshot:
            fail("dependency_pagination_snapshot_changed")
        entries=page.get("items")
        if not isinstance(entries,list):
            fail("dependency_items_not_array")
        for e in entries:
            if not isinstance(e,dict) or not isinstance(e.get("windowStart"),str) or not isinstance(e.get("windowEnd"),str):
                fail("dependency_interval_invalid")
            try:
                begin=dt.datetime.fromisoformat(e["windowStart"].replace("Z","+00:00")).timestamp()
                end=dt.datetime.fromisoformat(e["windowEnd"].replace("Z","+00:00")).timestamp()
            except ValueError:
                fail("dependency_interval_time_invalid")
            if begin>=end:
                fail("dependency_window_invalid")
            windows.append((begin,end))
        loops+=1
        if loops>100:
            fail("dependency_pagination_limit")
        if page["complete"] is True:
            if page.get("nextCursor"):
                fail("contradictory_dependency_complete")
            break
        cursor=page.get("nextCursor")
        if not isinstance(cursor,str) or not cursor:
            fail("dependency_pagination_incomplete")
    return windows,initial_snapshot

def get_candidates(root: Path, windows, now):
    state=root/"state"
    hourly=root/"hourly"
    if root.resolve()!=ROOT or not hourly.is_dir() or not state.is_dir() or hourly.is_symlink() or state.is_symlink():
        fail("unexpected_root_or_state")
    matches=[]
    stats={"receipts":0,"confirmed":0,"unverified":0,"not_mature":0,"held":0}
    for file in state.glob("hourly-*.json"):
        stats["receipts"]+=1
        if file.is_symlink() or not file.is_file():
            fail("unsafe_state_path")
        try:
            record=json.loads(file.read_text())
        except (OSError,ValueError):
            fail("invalid_receipt")
        if not isinstance(record,dict):
            fail("invalid_receipt_shape")
        name=record.get("source")
        if not isinstance(name,str) or not name.startswith("/archive/hourly/"):
            continue
        srcname=Path(name).name
        if Path(name)!=Path("/archive/hourly")/srcname:
            fail("unsafe_receipt_source")
        start=start_epoch(srcname)
        if start is None:
            continue
        source=hourly/srcname
        if not source.exists():
            continue
        meta=source.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or source.is_symlink() or source.resolve()!=source:
            fail("unexpected_recording_file_type")
        if not (record.get("confirmed") is True and isinstance(record.get("video_id"),str) and VIDEO.fullmatch(record["video_id"]) and isinstance(record.get("confirmed_epoch"),(int,float)) and record["confirmed_epoch"]<=now):
            stats["unverified"]+=1
            continue
        stats["confirmed"]+=1
        if start+3600+MIN_FINISH_AGE>now or meta.st_mtime>now-MIN_FILE_IDLE:
            stats["not_mature"]+=1
            continue
        # Recorded episode windows may straddle any hourly source. Never reclaim overlap.
        end=start+3600
        if any(begin<end and finish>start for begin,finish in windows):
            stats["held"]+=1
            continue
        if os.environ.get("FGB_OFFSITE_REQUIRED","0")=="1":
            receipt=root/"offsite"/(srcname+".sha256")
            try:
                expected=receipt.read_text().split()[0]
                with source.open("rb") as handle:
                    actual=hashlib.file_digest(handle,"sha256").hexdigest()
                if not re.fullmatch(r"[a-f0-9]{64}",expected) or actual!=expected:
                    stats["held"]+=1
                    continue
            except (OSError,ValueError,IndexError):
                stats["held"]+=1
                continue
        matches.append((source,file,meta,record["video_id"],record["confirmed_epoch"]))
    matches.sort(key=lambda x:x[0].name)
    if len(matches)>MAX_COUNT:
        matches=matches[:MAX_COUNT]
    return matches,stats

def verify_youtube(youtube,token,items):
    ids=sorted(set(c[3] for c in items))
    accepted={}
    for n in range(0,len(ids),50):
        response=youtube(token,"videos",params={"part":"id,snippet,status,processingDetails","id":",".join(ids[n:n+50]),"maxResults":"50"})
        for video in response.get("items") or []:
            ident=video.get("id")
            snippet=video.get("snippet") or {}
            status=video.get("status") or {}
            detail=video.get("processingDetails") or {}
            accepted[ident]=(
                isinstance(ident,str) and ident in ids
                and snippet.get("channelId")==CHANNEL
                and status.get("uploadStatus")=="processed"
                and detail.get("processingStatus") in ("succeeded",None)
            )
    return accepted

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--apply",action="store_true")
    args=a.parse_args()
    mod=runpy.run_path(AUTH_PATH)
    api=mod["api_call"]
    youtube=mod["youtube_json"]
    token,_=mod["get_token"]()
    found_channel,_=mod["verify_channel"](token)
    if found_channel != CHANNEL:
        fail("wrong_youtube_channel")
    if os.environ.get("FGB_OFFSITE_REQUIRED","0") not in ("0","1"):
        fail("offsite_configuration_invalid")
    before=dt.datetime.now(dt.timezone.utc).timestamp()
    windows,snapshot=deps(api)
    matches,stats=get_candidates(ROOT,windows,before)
    statuses=verify_youtube(youtube,token,matches)
    approved=[c for c in matches if statuses.get(c[3]) is True]
    rejected=len(matches)-len(approved)
    print("FGB_RECLAIM_PRECHECK "+json.dumps({
        "mode":"apply" if args.apply else "dry_run",
        "snapshot":snapshot,"active_episode_windows":len(windows),
        "receipt_counts":stats,"eligible_local":len(matches),
        "youtube_processed_and_correct_channel":len(approved),
        "youtube_unverified":rejected,
        "reclaimable_gib":round(sum(c[2].st_size for c in approved)/1024**3,3)
    },sort_keys=True),flush=True)
    if rejected:
        fail("youtube_status_unverified_do_not_delete_anything")
    if not args.apply:
        return
    if os.environ.get("FGB_ARCHIVE_RECLAIM_APPROVED")!="yes":
        fail("explicit_execution_gate_missing")
    # A second authenticated snapshot closes the most important TOCTOU window.
    second,snapshot2=deps(api)
    if second!=windows or snapshot2 is None:
        fail("episode_dependencies_changed")
    fresh=time.time()
    deleted=0
    freed=0
    for path,receipt,expected,vid,confirm in approved:
        # Revalidate state/file and re-read episode registry before each unlink.
        current_windows,_=deps(api)
        if current_windows!=windows:
            fail("episode_dependencies_changed_mid_batch")
        if not path.exists() or path.is_symlink():
            continue
        meta=path.lstat()
        if (meta.st_ino!=expected.st_ino or meta.st_size!=expected.st_size or meta.st_mtime_ns!=expected.st_mtime_ns or meta.st_nlink!=1 or
                meta.st_mtime>fresh-MIN_FILE_IDLE or path.resolve()!=path):
            fail("recording_changed_during_preflight")
        record=json.loads(receipt.read_text())
        if (record.get("confirmed") is not True or record.get("video_id")!=vid or record.get("confirmed_epoch")!=confirm or Path(record.get("source",""))!=Path("/archive/hourly")/path.name):
            fail("receipt_changed_during_preflight")
        # Parent uploader runs independently. Guard exceptions fail closed.
        path.unlink()
        deleted+=1
        freed+=meta.st_size
        print("FGB_RECLAIM_REMOVED "+path.name+" "+str(meta.st_size),flush=True)
    print("FGB_RECLAIM_RESULT "+json.dumps({"removed":deleted,"freed_gib":round(freed/1024**3,3),"source_only":True,"state_receipts_preserved":True}),flush=True)

if __name__=="__main__":
    main()

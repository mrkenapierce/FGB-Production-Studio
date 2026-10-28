#!/usr/bin/env python3
"""CNT rolling-buffer cleanup: complete remote dependencies plus durable local holds."""
import datetime, fcntl, importlib.util, json, os, pathlib, shutil, subprocess, sys, time
ROOT = pathlib.Path("/srv/cnt-archive")
def pending_windows(data):
    dep = data.get("dependencies", {})
    if data.get("ok") is not True or dep.get("complete") is not True or dep.get("nextCursor") is not None:
        raise ValueError("Incomplete dependency inventory; refusing cleanup")
    stamp = datetime.datetime.fromisoformat(dep["snapshotAt"].replace("Z","+00:00")).timestamp()
    if not -60 <= time.time()-stamp < 120:
        raise ValueError("Stale dependency snapshot")
    windows=[]
    for d in dep["items"]:
        a=datetime.datetime.fromisoformat(d["windowStart"].replace("Z","+00:00")).timestamp()
        b=datetime.datetime.fromisoformat(d["windowEnd"].replace("Z","+00:00")).timestamp()
        if b <= a: raise ValueError("Invalid dependency window")
        # Retain every returned dependency, including failed/disabled episodes.
        windows.append((a,b))
    return windows
def eligible(start,end,mtime,now,newest,held,windows):
    return (not newest and not held and now-max(end,mtime)>=10800
            and not any(a<end and b>start for a,b in windows))
def run():
    spec=importlib.util.spec_from_file_location("legacy","/opt/epic-archive-cleanup/archive-cleanup.py")
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    state=ROOT/"state"; scan=ROOT/"rolling"
    assert ROOT.resolve()==ROOT and not scan.is_symlink() and not state.is_symlink()
    status={"channel":"cnt","mode":"apply","deleted_count":0,"deleted_bytes":0,"protected_count":0,"error":None}
    try:
      with (state/"cleanup.lock").open("a+") as outer, (state/"retention.lock").open("r+") as lock:
        fcntl.flock(outer,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(lock,fcntl.LOCK_EX)
        now=time.time()
        subprocess.run(["docker","exec","epic-cnt-archive-worker","ffprobe","-version"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        data=legacy.signed_post(os.environ["CNT_ARCHIVE_URL"],"cnt",os.environ,json.dumps({"action":"episode_jobs"}))
        windows=pending_windows(data)
        held,ok=legacy.read_holds(state,["episode_hold","daily_hold"],now,600)
        if not ok: raise ValueError("Stale/missing holds; refusing cleanup")
        for p in (state/"dependencies").glob("*.json"):
            if p.is_symlink(): raise ValueError("Symlink dependency")
            d=json.loads(p.read_text())
            if d.get("channel")!="cnt": raise ValueError("Wrong dependency channel")
            if d.get("status")!="confirmed":
                a,b=d["start"],d["end"]
                if not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or b<=a: raise ValueError("Invalid local window")
                windows.append((a,b))
        files=[p for p in scan.glob("live-*.ts") if p.is_file() and not p.is_symlink()]
        starts={p:legacy.start_epoch(p.name) for p in files}
        newest=max((v for v in starts.values() if v is not None),default=None)
        for p,start in starts.items():
            st=p.stat()
            if start is None or start==newest or p.name in held or now-st.st_mtime<10800:
                status["protected_count"]+=1;continue
            try:
                length=float(subprocess.check_output(["docker","exec","epic-cnt-archive-worker","ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0","/cnt-archive/rolling/"+p.name],timeout=20,stderr=subprocess.DEVNULL))
            except Exception:
                status["protected_count"]+=1;continue
            if not 0<length<7200 or not eligible(start,start+length,st.st_mtime,now,False,False,windows):
                status["protected_count"]+=1;continue
            if p.is_symlink() or p.stat()!=st: raise ValueError("File changed during cleanup")
            p.unlink()
            status["deleted_count"]+=1;status["deleted_bytes"]+=st.st_size
        status["pending_windows"]=len(windows)
    except Exception as exc:
        status["error"]=type(exc).__name__+": "+str(exc)[:200]
    status["last_run"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
    status["disk_free_mb"]=int(shutil.disk_usage(ROOT).free/1048576)
    tmp=state/"cleanup-status.json.tmp"
    tmp.write_text(json.dumps(status));os.replace(tmp,state/"cleanup-status.json")
    print(json.dumps(status))
    return 1 if status["error"] else 0
if __name__=="__main__":
    if "--test" in sys.argv:
        assert eligible(0,600,600,20000,False,False,[])
        assert not eligible(0,600,600,20000,False,False,[(599,700)])
        assert not eligible(0,600,600,20000,True,False,[])
        assert not eligible(0,600,600,20000,False,True,[])
        assert not eligible(0,600,600,1000,False,False,[])
        for value in ({},{"ok":True,"dependencies":{"complete":False}}):
            try: pending_windows(value)
            except ValueError: pass
            else: raise AssertionError("Incomplete snapshot accepted")
        print("CNT retention safety tests passed")
    else: sys.exit(run())

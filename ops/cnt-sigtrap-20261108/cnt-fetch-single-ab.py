#!/usr/bin/env python3
"""CNT-only 80s A/B test of 5s creative/sponsor HTTP polling, self-restoring at 90s."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

SRC=Path("/opt/cnt/capture-watchdog.py")
START=r"""(() => {
  const k = "__CNT_FETCH_AB_NOV8__";
  if (window[k]) return {status:"already_active"};
  const oldFetch=window.fetch;
  let rejected=0;
  const wrapped=function(resource,init) {
    const url=typeof resource==="string"?resource:(resource && resource.url)||"";
    if (/\/api\/public\/fgbears\/(?:creatives|sponsors)(?:\?|$)/.test(url)) {
      rejected+=1;
      return Promise.reject(new Error("CNT temporary feed test"));
    }
    return Reflect.apply(oldFetch,this,arguments);
  };
  window[k]={oldFetch:oldFetch,wrapped:wrapped};
  window.fetch=wrapped;
  setTimeout(()=>{if(window.fetch===wrapped)window.fetch=oldFetch;delete window[k];},90000);
  return {status:"active",test:"creatives_and_sponsors"};
})()"""
END=r"""(() => {
  const k="__CNT_FETCH_AB_NOV8__";
  const x=window[k];
  if(!x) return {status:"already_restored"};
  if(window.fetch===x.wrapped)window.fetch=x.oldFetch;
  delete window[k];
  return {status:"restored"};
})()"""


def topfd():
    entries=[]
    for n in os.listdir("/proc"):
        if not n.isdigit(): continue
        p=Path("/proc")/n
        try:
            if (p/"comm").read_text().strip()!="chromium": continue
            count=sum(1 for _ in (p/"fd").iterdir())
            entries.append((int(n),count))
        except (OSError,ValueError): continue
    return max(entries,key=lambda x:x[1]) if entries else None


def main():
    feed=sys.argv[1] if len(sys.argv)>1 else ""
    if feed not in ("creatives","sponsors"):
        print("FETCH_AB=INVALID_FEED",flush=True);return 1
    print("FETCH_AB_FEED="+feed,flush=True)
    if not SRC.is_file():
        print("FETCH_AB=BLOCKED_SOURCE_UNAVAILABLE",flush=True);return 1
    spec=importlib.util.spec_from_file_location("cnt_wd",SRC)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg=mod.cfg_for("cnt")
    reason,_=mod.probe(cfg)
    if reason!="ok":
        print("FETCH_AB=BLOCKED_PAGE_UNHEALTHY_"+str(reason),flush=True);return 1
    target=mod.http_json("http://127.0.0.1:9223/json/list",3)
    candidates=[p for p in target if "/channels/cruisenewstrivia/broadcast" in p.get("url","") and p.get("type")=="page"]
    if len(candidates)!=1:
        print("FETCH_AB=BLOCKED_TARGET_COUNT_"+str(len(candidates)),flush=True);return 1
    ws=candidates[0].get("webSocketDebuggerUrl")
    if not ws:
        print("FETCH_AB=BLOCKED_NO_CDP",flush=True);return 1
    initial=topfd()
    if not initial:
        print("FETCH_AB=BLOCKED_NO_CHROMIUM_PROCESS",flush=True);return 1
    started=False
    try:
        res=mod.ws_eval(ws,START.replace("creatives|sponsors",feed).replace("creatives_and_sponsors",feed),5)
        if res.get("status")!="active":
            print("FETCH_AB=BLOCKED_START_RESULT_"+str(res.get("status")),flush=True);return 1
        started=True
        print("FETCH_AB=ACTIVE_ONLY_CREATIVE_AND_SPONSOR_HTTP",flush=True)
        time.sleep(60)
        later=topfd()
        if not later or initial[0]!=later[0]:
            print("FETCH_AB=INCOMPLETE_RENDERER_CHANGED",flush=True);return 1
        print("FETCH_AB_FD_DELTA_60S="+str(later[1]-initial[1]),flush=True)
        print("FETCH_AB_CONCLUSION="+("TARGET_FEED_CORRELATED" if later[1]-initial[1]<=7 else "TARGET_FEED_NOT_SOLE_CAUSE"),flush=True)
        return 0
    except Exception as e:
        print("FETCH_AB=INCOMPLETE_"+type(e).__name__,flush=True);return 1
    finally:
        if started:
            try:
                res=mod.ws_eval(ws,END,5)
                print("FETCH_AB_RESTORE="+str(res.get("status")),flush=True)
            except Exception:
                print("FETCH_AB_RESTORE=SELF_EXPIRES_AT_90S",flush=True)


if __name__=="__main__":
    sys.exit(main())

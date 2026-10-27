#!/usr/bin/env python3
"""CNT-only page replacement, preserving encoder and Chromium parent."""
import importlib.util,json,time,urllib.request,urllib.parse
spec=importlib.util.spec_from_file_location("probe","/tmp/cnt-renderer-probe.py")
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
base="http://127.0.0.1:9223"
def req(path,method=None):
    with urllib.request.urlopen(urllib.request.Request(base+path,method=method),timeout=5) as r:
        data=r.read()
        try:return json.loads(data)
        except ValueError:return None
def main():
    pages=[t for t in req("/json/list") if t.get("type")=="page" and "/channels/cruisenewstrivia/broadcast" in t.get("url","")]
    if len(pages)!=1:raise RuntimeError("Expected exactly one CNT page")
    old=pages[0]
    parsed=urllib.parse.urlsplit(old["url"])
    if parsed.scheme!="https" or parsed.hostname!="epiccontentcreatorgrants.org":raise RuntimeError("Unexpected CNT origin")
    with urllib.request.urlopen(old["url"],timeout=10) as r:
        if r.status!=200:raise RuntimeError("Origin unavailable")
    new=req("/json/new?"+urllib.parse.quote(old["url"],safe=":/?=&"),"PUT")
    ready=False
    for _ in range(8):
        time.sleep(2)
        try:
            if p.evaluate_in_target(new["webSocketDebuggerUrl"]):ready=True;break
        except Exception:pass
    if not ready:
        req("/json/close/"+new["id"])
        raise RuntimeError("Replacement not ready; original preserved")
    req("/json/activate/"+new["id"])
    req("/json/close/"+old["id"])
    p.main()
    print("CNT_PAGE_REPLACEMENT_VERIFIED")
if __name__=="__main__":main()

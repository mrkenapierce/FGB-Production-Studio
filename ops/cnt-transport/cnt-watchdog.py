#!/usr/bin/env python3
"""CNT-only question parity guard; no access to FGB service or secret keys."""
import base64, json, os, pathlib, socket, struct, subprocess, sys, time, urllib.parse, urllib.request
PAGE="https://epiccontentcreatorgrants.org/channels/cruisenewstrivia/broadcast"
API="https://epiccontentcreatorgrants.org/api/public/fgbears/game-screen"
STATE=pathlib.Path("/var/lib/cnt-watchdog/state.json")
def execute(args,timeout=16):
    return subprocess.run(args,capture_output=True,text=True,check=True,timeout=timeout).stdout.strip()
def network_api():
    # Origin requests sometimes stall, while an immediate subsequent request
    # succeeds. Retry one bounded GET; never synthesize/carry forward a question.
    last_error=None
    for attempt in range(2):
        try:
            raw=execute(["docker","exec","epic-cnt-capture","curl","-4","-fsS",
                         "--connect-timeout","2","--max-time","5",API],9)
            return json.loads(raw)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
            last_error=exc
            if attempt==0:time.sleep(1)
    raise RuntimeError("GAME_SOURCE_UNAVAILABLE") from last_error
def websocket(mode):
    tabs=json.load(urllib.request.urlopen("http://127.0.0.1:9223/json/list",timeout=4))
    pages=[x for x in tabs if x.get("type")=="page"]
    if len(pages)!=1 or pages[0].get("url")!=PAGE: raise RuntimeError("wrong CNT tab/URL")
    ws=urllib.parse.urlsplit(pages[0]["webSocketDebuggerUrl"])
    sock=socket.create_connection((ws.hostname,ws.port),timeout=5);sock.settimeout(12)
    k=base64.b64encode(os.urandom(16)).decode()
    hs=f"GET {ws.path} HTTP/1.1\r\nHost: {ws.hostname}:{ws.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {k}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    sock.sendall(hs.encode())
    buf=b""
    while b"\r\n\r\n" not in buf: buf+=sock.recv(4096)
    if b"101" not in buf.split(b"\r\n",1)[0]:raise RuntimeError("CDP socket unavailable")
    buf=buf.split(b"\r\n\r\n",1)[1]
    def take(n):
        nonlocal buf
        while len(buf)<n:buf+=sock.recv(65536)
        val,buf=buf[:n],buf[n:];return val
    if mode=="inspect":
        expr="JSON.stringify({url:location.href,state:document.querySelector('[data-testid=broadcast-scene]')?.getAttribute('data-state')||'',prompt:(document.querySelector('[data-testid=prompt]')?.textContent||'').trim()})"
        msg={"id":1,"method":"Runtime.evaluate","params":{"expression":expr,"returnByValue":True}}
    else:msg={"id":1,"method":"Page.reload","params":{"ignoreCache":True}}
    raw=json.dumps(msg).encode();mask=os.urandom(4);n=len(raw)
    header=bytes([129,128|n]) if n<126 else bytes([129,254])+struct.pack("!H",n)
    sock.sendall(header+mask+bytes(v^mask[i%4] for i,v in enumerate(raw)))
    while True:
        head=take(2);n=head[1]&127
        if n==126:n=struct.unpack("!H",take(2))[0]
        elif n==127:n=struct.unpack("!Q",take(8))[0]
        im=take(4) if head[1]&128 else None
        dat=take(n)
        if im:dat=bytes(v^im[i%4] for i,v in enumerate(dat))
        if head[0]&15!=1:continue
        msg=json.loads(dat)
        if msg.get("id")!=1:continue
        sock.close()
        if "error" in msg:raise RuntimeError(str(msg["error"]))
        if mode=="reload":return {"reloaded":True}
        val=msg.get("result",{}).get("result",{}).get("value")
        if not val:raise RuntimeError("empty CNT browser response")
        return json.loads(val)
def browser(mode):
    pid=execute(["docker","inspect","-f","{{.State.Pid}}","epic-cnt-capture"])
    out=execute(["nsenter","-t",pid,"-n",sys.executable,__file__,"--cdp",mode],23)
    return json.loads(out)
def main(repair):
    now=int(time.time())
    try: st=json.loads(STATE.read_text())
    except (OSError,ValueError):st={"failures":0,"since":0,"last_reload":0}
    result={"utc":now,"mode":"repair" if repair else "read-only"}
    try:
        feed=network_api()
        active=feed.get("phase") in ("question","revealed") and feed.get("presentationType")=="question" and bool(feed.get("prompt"))
    except Exception as exc:
        result["state"]="SOURCE_UNAVAILABLE_NO_RELOAD";result["error"]=type(exc).__name__
        # A timeout cannot prove that the browser is out of sync. Preserve
        # prior mismatch evidence, but never initiate recovery on this read.
        active=False
    if "state" not in result and not active:
        result["state"]="NOT_ACTIVE_QUESTION";st["failures"]=0
    if active:
        try:
            scene=browser("inspect");expected=" ".join(feed["prompt"].split())
            got=" ".join(scene.get("prompt","").split())
            match=(scene.get("url")==PAGE and scene.get("state") in ("question","reveal") and expected==got)
            result["scene"]=scene.get("state")
        except Exception as exc:
            match=False;result["error"]=type(exc).__name__
        if match:result["state"]="QUESTION_MATCH";st["failures"]=0
        else:
            if now-st.get("since",0)>180:st["failures"]=0;st["since"]=now
            st["failures"]+=1;result["state"]="QUESTION_MISMATCH";result["failures"]=st["failures"]
            if repair and st["failures"]>=2 and now-st.get("last_reload",0)>=1800:
                try:
                    browser("reload");st["last_reload"]=now;st["failures"]=0
                    result["state"]="CNT_TAB_RELOAD_ONLY"
                except Exception as exc:result["state"]="RELOAD_BLOCKED";result["error"]=type(exc).__name__
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(st))
    print(json.dumps(result),flush=True)
    return 0
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--cdp":
        try:print(json.dumps(websocket(sys.argv[2])))
        except Exception as exc:
            print(json.dumps({"error":type(exc).__name__}));sys.exit(1)
    else:sys.exit(main("--repair" in sys.argv))

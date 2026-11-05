#!/usr/bin/env python3
"""Capture-browser health probe and bounded restart policy.

Called once per tick by the EXISTING capture loop (run-cnt.sh). It is not a
daemon: it probes, decides, records telemetry and prints ONE action word that
the loop acts on:

    ok [detail]        page healthy
    hold <reason>      unhealthy but not restarting yet (threshold, cooldown,
                       hourly cap, site outage, startup grace, lock held)
    restart <reason>   the loop should restart Chromium now

Why: the previous loop only asked the BROWSER process (/json/version). A
crashed renderer (Chromium "Aw, Snap" / SIGTRAP) leaves that process and
FFmpeg alive, so the dead page stayed on air until the 6-hour refresh. This
probe asks the PAGE itself over the local DevTools socket.

Never restarts on a site/network outage (restarting cannot fix it), never
restarts more often than the backoff allows, never exits non-zero, never sends
anything off-host except a plain GET of the public broadcast page, and never
reads or logs stream keys.

Usage: capture-watchdog.py <channel> tick [--process-exited] | started | status
"""
import base64, fcntl, glob, json, os, re, socket, struct, sys, time, urllib.parse, urllib.request

CHANNELS = {
    "cnt": {"port": 9223, "path": "/channels/cruisenewstrivia/broadcast", "dir": "/tmp/cnt-watchdog", "env": "CNT"},
    # Compatible configuration for the FGB capture. NOT wired into any FGB
    # script: FGB production transport lives in the external studio repo.
    "fgb": {"port": 9222, "path": "/fgb-broadcast", "dir": "/tmp/fgb-watchdog", "env": "FGB"},
}

DEFAULTS = {
    "fail_threshold": 3,       # consecutive bad probes (~15 s at a 5 s tick)
    "startup_grace": 60,       # seconds after a (re)start before probes count
    "base_cooldown": 30,       # first restart may follow the previous after 30 s
    "max_cooldown": 600,       # backoff doubles up to 10 min between restarts
    "healthy_reset": 600,      # 10 min continuously healthy resets the backoff
    "max_per_hour": 6,         # hard cap on watchdog restarts in any 60 min
    "http_timeout": 3.0,
    "ws_timeout": 5.0,
    "origin_timeout": 5.0,
}

PAGE_FAILURES = {"no_page_target", "page_error", "wrong_page", "scene_missing", "page_loading"}
CRASH_PATTERNS = re.compile(r"SIGTRAP|SIGSEGV|SIGILL|SIGBUS|Received signal|crash|Check failed|FATAL|Out of memory|OOM|oom|renderer|Renderer|GPU process|shared memory|/dev/shm", re.I)
SECRETISH = re.compile(r"(?:https?|rtmps?|wss?)://[^\s\"<>]+|(?:[\w-]*(?:key|token|secret|signature|credential|authorization)[\w-]*)\s*[:=]\s*[^\s,;]+|Bearer\s+\S+", re.I)
EVENTS_MAX_BYTES = 1_000_000
CHROME_LOG_MAX_BYTES = 5_000_000

PROBE_JS = r"""(async () => {
  const raf = await Promise.race([
    new Promise(r => requestAnimationFrame(() => r(true))),
    new Promise(r => setTimeout(() => r(false), 2000)),
  ]);
  const scene = document.querySelector('[data-testid="broadcast-scene"]');
  return { path: location.pathname, readyState: document.readyState, hasScene: !!scene,
           sceneState: scene ? scene.getAttribute('data-state') : null, raf,
           heapMb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null };
})()"""


def cfg_for(channel, env=os.environ):
    if channel not in CHANNELS:
        raise SystemExit(f"unknown channel {channel!r}")
    base = dict(CHANNELS[channel]); prefix = base["env"]
    c = dict(DEFAULTS)
    for k in DEFAULTS:
        v = env.get(f"{prefix}_WATCHDOG_{k.upper()}")
        if v:
            try:
                value = float(v) if "timeout" in k else int(v)
                if 0 < value <= (30 if "timeout" in k else 3600): c[k] = value
            except ValueError: pass
    c.update(base)
    c["dir"] = env.get(f"{prefix}_WATCHDOG_DIR") or base["dir"]
    c["origin"] = (env.get("BROADCAST_ORIGIN") or "").rstrip("/")
    c["chrome_log"] = env.get(f"{prefix}_CHROME_LOG") or os.path.join(c["dir"], "chromium.log")
    c["chrome_log_owned"] = env.get(f"{prefix}_CHROME_LOG_OWNED") == "1"
    c["profile"] = env.get(f"{prefix}_CHROME_PROFILE") or f"/tmp/{channel}-chrome"
    c["channel"] = channel
    return c


# ---------------------------------------------------------------- DevTools I/O
def http_json(url, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace"))


def _ws_frame(payload: bytes) -> bytes:
    n = len(payload); head = bytes([0x81])
    if n < 126: head += bytes([0x80 | n])
    elif n < 65536: head += bytes([0x80 | 126]) + struct.pack(">H", n)
    else: head += bytes([0x80 | 127]) + struct.pack(">Q", n)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk: raise ConnectionError("socket closed")
        buf += chunk
    return buf


def _ws_read(s):
    """Return one complete text message (reassembling fragments)."""
    parts = []
    while True:
        b1, b2 = _recv_exact(s, 2)
        op, n = b1 & 0x0F, b2 & 0x7F
        if n == 126: n = struct.unpack(">H", _recv_exact(s, 2))[0]
        elif n == 127: n = struct.unpack(">Q", _recv_exact(s, 8))[0]
        if n > 1_000_000 or sum(len(p) for p in parts) + n > 1_000_000:
            raise ConnectionError("oversize debugger frame")
        mask = _recv_exact(s, 4) if b2 & 0x80 else None
        data = _recv_exact(s, n) if n else b""
        if mask: data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op == 0x8: raise ConnectionError("websocket closed by peer")
        if op == 0x9:
            pong = bytearray(_ws_frame(data)); pong[0] = 0x8A
            s.sendall(pong); continue
        if op in (0x1, 0x0): parts.append(data)
        if b1 & 0x80 and op in (0x1, 0x0): return b"".join(parts).decode("utf-8", "replace")


def ws_eval(ws_url, expression, timeout):
    """Evaluate in the page. Raises TimeoutError (frozen) / RuntimeError('crashed')."""
    u = urllib.parse.urlparse(ws_url)
    s = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            # Byte reads avoid losing a coalesced first WebSocket frame.
            if len(head) >= 16_384: raise ConnectionError("oversize handshake")
            chunk = s.recv(1)
            if not chunk: raise ConnectionError("handshake closed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]: raise ConnectionError("handshake refused")
        s.sendall(_ws_frame(json.dumps({"id": 1, "method": "Inspector.enable"}).encode()))
        s.sendall(_ws_frame(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True, "timeout": int(timeout * 1000)}}).encode()))
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() > deadline: raise TimeoutError("evaluate timeout")
            s.settimeout(max(0.01, deadline - time.monotonic()))
            msg = json.loads(_ws_read(s))
            if msg.get("method") in ("Inspector.targetCrashed", "Inspector.detached"):
                raise RuntimeError("crashed")
            if msg.get("id") == 2:
                if "error" in msg: raise RuntimeError(str(msg["error"].get("message", "error"))[:120])
                res = msg.get("result", {})
                if "exceptionDetails" in res: raise RuntimeError("page exception")
                return res.get("result", {}).get("value") or {}
    except socket.timeout as e:
        raise TimeoutError("evaluate timeout") from e
    finally:
        try: s.close()
        except OSError: pass


# ---------------------------------------------------------------- probe
def probe(c, process_exited=False, get=http_json, evaluate=ws_eval):
    """Classify page health. Returns (reason, detail). reason 'ok' = healthy."""
    if process_exited: return "browser_process_exited", {}
    base = f"http://127.0.0.1:{c['port']}"
    try: get(f"{base}/json/version", c["http_timeout"])
    except Exception: return "browser_unreachable", {}
    try: targets = get(f"{base}/json/list", c["http_timeout"])
    except Exception: return "browser_unreachable", {}
    pages = [t for t in targets if t.get("type") == "page"]
    if not pages: return "no_page_target", {}
    want = [t for t in pages if urllib.parse.urlparse(t.get("url", "")).path == c["path"]
            and (not c["origin"] or t.get("url", "").split("?", 1)[0] == c["origin"] + c["path"])]
    if not want:
        url = pages[0].get("url", "")
        if url.startswith("chrome-error://"): return "page_error", {"url": "chrome-error"}
        return "wrong_page", {}
    t = want[0]
    if not t.get("webSocketDebuggerUrl"): return "renderer_unresponsive", {"why": "no debugger url"}
    debugger = urllib.parse.urlparse(t["webSocketDebuggerUrl"])
    if debugger.scheme != "ws" or debugger.hostname not in ("127.0.0.1", "localhost") or debugger.port != c["port"]:
        return "renderer_unresponsive", {"why": "invalid debugger address"}
    try: info = evaluate(t["webSocketDebuggerUrl"], PROBE_JS, c["ws_timeout"])
    except TimeoutError: return "renderer_unresponsive", {}
    except RuntimeError: return "renderer_crashed", {"why": "page evaluation failed"}
    except Exception as e: return "renderer_unresponsive", {"why": type(e).__name__}
    detail = {k: info.get(k) for k in ("readyState", "hasScene", "sceneState", "raf", "heapMb")}
    if info.get("readyState") != "complete": return "page_loading", detail
    if not info.get("hasScene"): return "scene_missing", detail
    if info.get("raf") is False: return "renderer_unresponsive", detail
    return "ok", detail


def origin_reachable(c, opener=urllib.request.urlopen):
    if not c["origin"]: return True   # unknown origin: do not block recovery
    try:
        with opener(urllib.request.Request(c["origin"] + c["path"], method="GET"), timeout=c["origin_timeout"]) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


# ---------------------------------------------------------------- policy
def cooldown(c, level):
    return min(c["base_cooldown"] * (2 ** max(level - 1, 0)), c["max_cooldown"]) if level > 0 else 0


def decide(st, reason, now, c, origin_ok=lambda: True):
    """Pure-ish policy (origin_ok is only called when needed). Mutates st."""
    st.setdefault("restarts", []); st.setdefault("level", 0); st.setdefault("fails", 0)
    st["restarts"] = [t for t in st["restarts"] if now - t < 3600]
    started = st.get("chrome_started", 0)
    if reason == "ok":
        recovered = st.get("fails", 0) > 0 or st.get("awaiting_ready")
        st["fails"] = 0
        if st.get("awaiting_ready"):
            st["last_ready_seconds"] = round(now - started, 1); st["awaiting_ready"] = False
        st.setdefault("healthy_since", now)
        if st["level"] and now - st["healthy_since"] >= c["healthy_reset"]: st["level"] = 0
        st["last_ok"] = now; st["last_reason"] = "ok"
        return ("ok", "recovered") if recovered else ("ok", "")
    st.pop("healthy_since", None)
    in_grace = now - started < c["startup_grace"]
    if in_grace and reason != "browser_process_exited":
        st["last_reason"] = reason; return "hold", "startup_grace"
    st["fails"] = st.get("fails", 0) + 1; st["last_reason"] = reason
    threshold = 1 if reason == "browser_process_exited" else c["fail_threshold"]
    if st["fails"] < threshold: return "hold", f"{reason} ({st['fails']}/{threshold})"
    if reason in PAGE_FAILURES and not origin_ok():
        st["outage"] = True; return "hold", "origin_unreachable"
    st["outage"] = False
    last = st["restarts"][-1] if st["restarts"] else 0
    wait = cooldown(c, st["level"])
    if last and now - last < wait: return "hold", f"cooldown {int(wait - (now - last))}s ({reason})"
    if len(st["restarts"]) >= c["max_per_hour"]: return "hold", f"hourly_cap ({reason})"
    st["restarts"].append(now); st["level"] += 1; st["fails"] = 0
    st["total_restarts"] = st.get("total_restarts", 0) + 1
    return "restart", reason


# ---------------------------------------------------------------- evidence
def _read(p, n=4096):
    try:
        with open(p) as f: return f.read(n)
    except OSError: return ""


def redact(s):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s))
    s = re.sub(r"Bearer\s+\S+", "[redacted]", s, flags=re.I)
    return SECRETISH.sub("[redacted]", s)


def sanitized(data):
    if isinstance(data, str): return redact(data)[:16_384]
    if isinstance(data, dict): return {k: sanitized(v) for k, v in data.items()}
    if isinstance(data, list): return [sanitized(v) for v in data]
    return data


def evidence(c):
    ev = {}
    mi = dict(re.findall(r"^(MemTotal|MemAvailable|SwapFree):\s+(\d+)", _read("/proc/meminfo"), re.M))
    ev["mem_mb"] = {k: int(v) // 1024 for k, v in mi.items()}
    for name, p in (("dev_shm", "/dev/shm"), ("tmp", "/tmp")):
        try:
            s = os.statvfs(p); ev[f"{name}_free_mb"] = s.f_bavail * s.f_frsize // 1048576
        except OSError: pass
    cg = _read("/sys/fs/cgroup/memory.events")
    if cg: ev["cgroup_memory_events"] = dict((k, int(v)) for k, v in re.findall(r"^(\w+) (\d+)", cg, re.M))
    cur, mx = _read("/sys/fs/cgroup/memory.current").strip(), _read("/sys/fs/cgroup/memory.max").strip()
    if cur.isdigit(): ev["cgroup_memory_mb"] = int(cur) // 1048576
    if mx: ev["cgroup_memory_max"] = mx if not mx.isdigit() else int(mx) // 1048576
    rss = n = 0
    for st in glob.glob("/proc/[0-9]*/status"):
        txt = _read(st, 2048)
        if re.search(r"^Name:\s+chrom", txt, re.M):
            n += 1; m = re.search(r"^VmRSS:\s+(\d+)", txt, re.M); rss += int(m.group(1)) if m else 0
    ev["chromium_processes"] = n; ev["chromium_rss_mb"] = rss // 1024
    ev["crash_lines"] = crash_lines(c["chrome_log"])
    dumps = glob.glob(os.path.join(c["profile"], "**", "*.dmp"), recursive=True)
    if dumps: ev["minidumps"] = len(dumps)
    return ev


def crash_lines(path, limit=15):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 64_000))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError: return []
    hits = [redact(l.strip())[:300] for l in tail if CRASH_PATTERNS.search(l) and "EPIC_AIR_BOUNDARY" not in l]
    return hits[-limit:]


# ---------------------------------------------------------------- state + telemetry
def _load(path):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError): return {}


def _save(path, data):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600); json.dump(sanitized(data), f)
    os.replace(tmp, path)


def append_event(c, ev):
    p = os.path.join(c["dir"], "events.jsonl")
    try:
        if os.path.getsize(p) > EVENTS_MAX_BYTES: os.replace(p, p + ".1")
    except OSError: pass
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as f:
        os.fchmod(f.fileno(), 0o600); f.write(json.dumps(sanitized(ev), separators=(",", ":")) + "\n")


def rotate_chrome_log(c):
    """Copy-truncate our own Chromium log (never the air observer's file)."""
    if not c["chrome_log_owned"]: return
    p = c["chrome_log"]
    try:
        if os.path.getsize(p) <= CHROME_LOG_MAX_BYTES: return
        with open(p, "rb") as f: f.seek(-1_000_000, 2); keep = f.read()
        with open(p + ".1", "wb") as f: f.write(keep)
        os.truncate(p, 0)
    except OSError: pass


def iso(t): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def run(channel, cmd, process_exited=False, now=None, env=os.environ, probe_fn=probe, origin_fn=origin_reachable):
    c = cfg_for(channel, env); os.makedirs(c["dir"], exist_ok=True)
    os.chmod(c["dir"], 0o700)
    now = time.time() if now is None else now
    state_p, lock_p = os.path.join(c["dir"], "state.json"), os.path.join(c["dir"], "tick.lock")
    if cmd == "status":
        print(json.dumps(_load(os.path.join(c["dir"], "status.json")), indent=2)); return "status"
    if cmd == "health":
        status = _load(os.path.join(c["dir"], "status.json"))
        try:
            probe_age = now - os.path.getmtime(os.path.join(c["dir"], "status.json"))
            encoder_age = now - os.path.getmtime("/tmp/cnt-ffmpeg.progress")
            return "healthy" if status.get("action") == "ok" and 0 <= probe_age < 20 and 0 <= encoder_age < 30 else "unhealthy"
        except OSError: return "unhealthy"
    with open(lock_p, "w") as lk:
        try: fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError: return "hold locked"
        st = _load(state_p)
        if channel == "cnt" and os.path.exists(state_p) and (not isinstance(st, dict) or not st):
            _save(os.path.join(c["dir"], "status.json"), {"channel": channel, "action": "hold", "alert": "state_invalid"})
            return "hold ALERT_state_invalid"
        if cmd == "started":
            st["chrome_started"] = now; st["awaiting_ready"] = True; st["fails"] = 0
            st.pop("healthy_since", None); _save(state_p, st)
            append_event(c, {"at": iso(now), "event": "chromium_started", "channel": channel}); return "started"
        reason, detail = probe_fn(c, process_exited)
        action, why = decide(st, reason, now, c, origin_ok=lambda: origin_fn(c))
        ev = {"at": iso(now), "channel": channel, "action": action, "reason": reason, "why": why, "detail": detail}
        if action == "restart":
            ev["evidence"] = evidence(c)
        # Preserve OOM/limit/disk evidence even while the origin is unavailable.
        if channel == "cnt" and now - st.get("last_evidence", 0) >= 60:
            ev["evidence"] = evidence(c); st["last_evidence"] = now
            append_event(c, {"at": iso(now), "channel": channel, "event": "resource_sample", "evidence": ev["evidence"]})
        exhausted = why.startswith("hourly_cap")
        if exhausted and not st.get("budget_alerted"):
            append_event(c, {**ev, "event": "ALERT_restart_budget_exhausted", "evidence": evidence(c)})
        st["budget_alerted"] = exhausted
        if action == "restart" or why == "recovered" or why == "origin_unreachable" or (action == "hold" and st.get("fails") == 1):
            if not (why == "origin_unreachable" and st.get("outage_logged")): append_event(c, ev)
        st["outage_logged"] = why == "origin_unreachable"
        st["last_probe"] = now; _save(state_p, st)
        _save(os.path.join(c["dir"], "status.json"), {
            "channel": channel, "last_probe": iso(now), "last_ok": iso(st.get("last_ok")),
            "action": action, "reason": reason, "why": why, "detail": detail,
            "consecutive_failures": st.get("fails", 0), "backoff_level": st.get("level", 0),
            "next_cooldown_seconds": cooldown(c, st.get("level", 0)),
            "restarts_last_hour": len(st.get("restarts", [])), "restarts_total": st.get("total_restarts", 0),
            "last_restart": iso(st["restarts"][-1]) if st.get("restarts") else None,
            "last_ready_seconds": st.get("last_ready_seconds"), "chromium_started": iso(st.get("chrome_started")),
            "origin_outage": bool(st.get("outage")),
            "alert": "restart_budget_exhausted" if exhausted else None,
        })
        rotate_chrome_log(c)
        return f"{action} {why or reason}".strip()


def main(argv):
    if len(argv) < 3 or argv[2] not in ("tick", "started", "status", "health"):
        print(__doc__.strip().splitlines()[-1]); return 2
    try: out = run(argv[1], argv[2], process_exited="--process-exited" in argv)
    except SystemExit: raise
    except Exception as e:   # never break the capture loop
        out = f"hold watchdog_error {type(e).__name__}"
    if out != "status": print(out)
    if argv[2] == "health": return 0 if out == "healthy" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
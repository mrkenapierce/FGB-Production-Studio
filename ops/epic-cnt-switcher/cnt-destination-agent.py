#!/usr/bin/env python3
"""CNT destination agent. INACTIVE until host-installed and operator-configured.

Pull-only: POSTs a signed status report to the app over HTTPS and applies a signed
instruction ({opId, alias, phase}) by atomically writing the allowlisted alias file that
run-cnt.sh (CNT_DESTINATION_SWITCHING=on) re-reads. It never kills processes, never
reads, logs or sends stream keys (only whether EPIC env is present), never follows
redirects, and accepts only fixed aliases. FGB is never touched.

Env (non-secret unless noted):
  CNT_DESTINATION_AGENT_URL   https://<site>/api/public/channels/cruisenewstrivia/destination-agent
  CNT_DESTINATION_AGENT_SECRET  (secret, >=32 chars; same value as the app secret)
  CNT_DESTINATION_SWITCHING=on  (host opt-in; also required by run-cnt.sh)
  CNT_DESTINATION_STATE=/cnt-state/destination   PROGRESS=/tmp/cnt-ffmpeg.progress
  EPIC_YOUTUBE_INGEST_URL / EPIC_YOUTUBE_STREAM_KEY  (only presence is reported)
"""
import fcntl, hashlib, hmac, json, os, re, secrets, sys, time, urllib.error, urllib.request

ALIASES = ("cnt", "epic_grants")
SKEW = 60
OP_RE = re.compile(r"^dst_[a-z0-9]{16,40}$")
MAX_BODY = 4096
POLL_SECONDS = 10

def log(msg):  # never pass secrets here
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "[cnt-destination-agent]", msg, flush=True)

def derive(secret, role):
    return hmac.new(secret.encode(), f"epic-destination:v2:{role}".encode(), hashlib.sha256).hexdigest()

def sign(secret, role, ts, nonce, body):
    return hmac.new(derive(secret, role).encode(), f"{ts}.{nonce}.{body}".encode(), hashlib.sha256).hexdigest()

class Journal:
    """Durable nonce + applied-op journal (survives restarts)."""
    def __init__(self, state):
        self.path = os.path.join(state, "journal.json")
        try:
            with open(self.path) as f: self.d = json.load(f)
        except (OSError, ValueError): self.d = {"nonces": {}, "lastOp": None}
    def seen(self, n): return n in self.d["nonces"]
    def add(self, n, now):
        self.d["nonces"] = {k: v for k, v in self.d["nonces"].items() if now - v < SKEW * 10}
        self.d["nonces"][n] = now; self.save()
    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f: json.dump(self.d, f)
        os.chmod(tmp, 0o600); os.replace(tmp, self.path)

def verify_response(secret, headers, body, now, journal):
    ts, nonce, sig = headers.get("x-epic-ts"), headers.get("x-epic-nonce"), headers.get("x-epic-sig")
    if not (ts and nonce and sig) or len(body) > MAX_BODY: return "malformed"
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", nonce) or not ts.isdigit(): return "malformed"
    if abs(now - int(ts)) > SKEW: return "stale"
    if not hmac.compare_digest(sign(secret, "app-to-agent", int(ts), nonce, body), sig): return "bad_signature"
    if journal.seen(nonce): return "replay"
    journal.add(nonce, now); return None

def parse_instruction(body):
    ins = json.loads(body).get("instruction")
    if ins is None: return None
    if set(ins) != {"opId", "alias", "phase"} or ins["alias"] not in ALIASES or ins["phase"] not in ("apply", "rollback") \
       or not OP_RE.match(str(ins["opId"])):
        raise ValueError("invalid instruction")
    return ins

def write_alias(state, alias):
    if alias not in ALIASES: raise ValueError("alias not allowlisted")
    with open(os.path.join(state, "switch.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one writer at a time
        tmp = os.path.join(state, "destination.next")
        with open(tmp, "w") as f: f.write(alias)
        os.chmod(tmp, 0o600); os.replace(tmp, os.path.join(state, "destination"))

def read_report(state, progress, last_op):
    applied, ff = None, "stopped"
    try:
        with open(os.path.join(state, "applied")) as f: a = json.load(f)
        if a.get("alias") in ALIASES: applied = a["alias"]
        pid = int(a.get("pid", 0))
        # Read-only liveness of run-cnt's OWN recorded ffmpeg pid; nothing is signalled.
        if pid > 1 and os.path.exists(f"/proc/{pid}") and b"ffmpeg" in open(f"/proc/{pid}/cmdline", "rb").read(): ff = "sending"
    except (OSError, ValueError): pass
    try: age = max(0, int(time.time() - os.stat(progress).st_mtime))
    except OSError: age = None
    if ff == "sending" and (age is None or age > 10): ff = "error"
    key = {"cnt": os.environ.get("CNT_YOUTUBE_STREAM_KEY"), "epic_grants": os.environ.get("EPIC_YOUTUBE_STREAM_KEY")}.get(applied or "")
    fp = hashlib.sha256(key.encode()).hexdigest() if key else None  # one-way; the key never leaves the host
    return {"applied": applied, "ffmpeg": ff, "progressAgeSec": age, "opId": last_op, "keyFingerprint": fp,
            "epicKeyConfigured": bool(os.environ.get("EPIC_YOUTUBE_INGEST_URL")) and bool(os.environ.get("EPIC_YOUTUBE_STREAM_KEY")),
            "switchingEnabled": os.environ.get("CNT_DESTINATION_SWITCHING") == "on"}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

def poll_once(cfg, journal, opener=None):
    body = json.dumps(read_report(cfg["state"], cfg["progress"], journal.d.get("lastOp")), separators=(",", ":"))
    ts, nonce = int(time.time()), secrets.token_hex(16)
    req = urllib.request.Request(cfg["url"], data=body.encode(), method="POST", headers={
        "content-type": "application/json", "x-epic-ts": str(ts), "x-epic-nonce": nonce,
        "x-epic-sig": sign(cfg["secret"], "agent-to-app", ts, nonce, body)})
    opener = opener or urllib.request.build_opener(NoRedirect)
    with opener.open(req, timeout=8) as r:
        raw = r.read(MAX_BODY + 1).decode()
        err = verify_response(cfg["secret"], {k.lower(): v for k, v in r.headers.items()}, raw, int(time.time()), journal)
    if err: log(f"response rejected: {err}"); return None
    ins = parse_instruction(raw)
    if ins:
        write_alias(cfg["state"], ins["alias"])
        journal.d["lastOp"] = ins["opId"]; journal.save()
        log(f"op {ins['opId']} {ins['phase']} -> {ins['alias']}")
    return ins

def load_config():
    url = os.environ.get("CNT_DESTINATION_AGENT_URL", "")
    secret = os.environ.get("CNT_DESTINATION_AGENT_SECRET", "")
    if not re.fullmatch(r"https://[a-z0-9.-]+/api/public/channels/cruisenewstrivia/destination-agent", url):
        raise SystemExit("config: CNT_DESTINATION_AGENT_URL must be the fixed https agent endpoint")
    if len(secret) < 32: raise SystemExit("config: CNT_DESTINATION_AGENT_SECRET missing or too short")
    if os.environ.get("CNT_DESTINATION_SWITCHING") != "on": raise SystemExit("config: CNT_DESTINATION_SWITCHING is not on; agent stays off")
    state = os.environ.get("CNT_DESTINATION_STATE", "/cnt-state/destination")
    os.makedirs(state, mode=0o700, exist_ok=True)
    return {"url": url, "secret": secret, "state": state, "progress": os.environ.get("PROGRESS", "/tmp/cnt-ffmpeg.progress")}

def main():
    cfg = load_config(); journal = Journal(cfg["state"]); backoff = POLL_SECONDS
    log("started (pull-only)")
    while True:
        try: poll_once(cfg, journal); backoff = POLL_SECONDS
        except (urllib.error.URLError, OSError, ValueError) as e:
            log(f"poll failed: {type(e).__name__}"); backoff = min(backoff * 2, 120)  # no body/secret in logs
        time.sleep(backoff)

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        import tempfile
        d = tempfile.mkdtemp(); j = Journal(d); s = "k" * 40; b = '{"instruction":null}'
        h = {"x-epic-ts": "1000", "x-epic-nonce": "n" * 20, "x-epic-sig": sign(s, "app-to-agent", 1000, "n" * 20, b)}
        assert verify_response(s, h, b, 1010, j) is None
        assert verify_response(s, h, b, 1010, Journal(d)) == "replay", "replay must survive restart"
        assert verify_response(s, dict(h, **{"x-epic-sig": sign(s, "agent-to-app", 1000, "m" * 20, b), "x-epic-nonce": "m" * 20}), b, 1010, j) == "bad_signature", "role separation"
        assert verify_response(s, dict(h, **{"x-epic-nonce": "p" * 20}), b, 1100, j) == "stale"
        for bad in ('{"instruction":{"opId":"dst_abcdefghij123456","alias":"rtmp://evil","phase":"apply"}}',
                    '{"instruction":{"opId":"x","alias":"cnt","phase":"apply"}}',
                    '{"instruction":{"opId":"dst_abcdefghij123456","alias":"cnt","phase":"apply","cmd":"rm"}}'):
            try: parse_instruction(bad); raise AssertionError("accepted bad instruction")
            except ValueError: pass
        write_alias(d, "epic_grants"); assert open(os.path.join(d, "destination")).read() == "epic_grants"
        os.environ.pop("EPIC_YOUTUBE_STREAM_KEY", None)
        r = read_report(d, "/nonexistent", None); assert r["applied"] is None and r["ffmpeg"] == "stopped" and r["epicKeyConfigured"] is False
        assert "KEY" not in json.dumps(r).upper().replace("EPICKEYCONFIGURED", "").replace("KEYFINGERPRINT", "")
        print("self-test ok"); sys.exit(0)
    main()
#!/usr/bin/env python3
"""FGB-only Chromium renderer watchdog. Never restarts FFmpeg, Docker, or CNT.

Host mode (systemd timer): checks the FGB capture *DOM renderer*, not merely
Chromium's process/DevTools port, and replaces only the dead FGB tab after
three consecutive failed probes. Container subcommands execute via docker exec.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

CONTAINER = "fgb-transport-youtube-1"
URL = "https://epiccontentcreatorgrants.org/fgb-broadcast?target=youtube"
DEVTOOLS = "http://127.0.0.1:9222"
STATE_DIR = Path("/var/lib/fgb-browser-watchdog")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "lock"
PROBE_FAIL_THRESHOLD = 3
RECOVERY_COOLDOWN_SECONDS = 180
RECOVERY_LIMIT_PER_HOUR = 3


def emit(kind: str, **details: object) -> None:
    print(json.dumps({"event": kind, "time": int(time.time()), **details}, sort_keys=True), flush=True)


def get_json(url: str, *, method: str = "GET", timeout: float = 6) -> dict | list:
    with urlopen(Request(url, method=method), timeout=timeout) as response:
        return json.load(response)


def tab_list() -> list[dict]:
    result = get_json(DEVTOOLS + "/json/list")
    return result if isinstance(result, list) else []


def broadcast_tabs() -> list[dict]:
    return [tab for tab in tab_list()
            if tab.get("type") == "page"
            and "/fgb-broadcast" in str(tab.get("url", ""))
            and "epiccontentcreatorgrants.org" in str(tab.get("url", ""))]


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RuntimeError("DevTools WebSocket closed")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = recv_exact(sock, 2)
    opcode = header[0] & 15
    length = header[1] & 127
    masked = bool(header[1] & 128)
    if length == 126:
        length = struct.unpack("!H", recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", recv_exact(sock, 8))[0]
    if length > 1_000_000:
        raise RuntimeError("Oversized DevTools frame")
    mask = recv_exact(sock, 4) if masked else b""
    data = recv_exact(sock, length)
    if mask:
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
    return opcode, data


def send_ws(sock: socket.socket, payload: bytes, opcode: int = 1) -> None:
    mask = os.urandom(4)
    size = len(payload)
    if size < 126:
        head = bytes((0x80 | opcode, 0x80 | size))
    elif size < 65536:
        head = bytes((0x80 | opcode, 0xFE)) + struct.pack("!H", size)
    else:
        head = bytes((0x80 | opcode, 0xFF)) + struct.pack("!Q", size)
    sock.sendall(head + mask + bytes(ch ^ mask[i % 4] for i, ch in enumerate(payload)))


def eval_tab(tab: dict) -> dict:
    ws = urlsplit(tab.get("webSocketDebuggerUrl", ""))
    if ws.scheme != "ws" or ws.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError("Unsafe or missing local DevTools target")
    path = ws.path + (("?" + ws.query) if ws.query else "")
    sock = socket.create_connection((ws.hostname, ws.port or 9222), timeout=5)
    sock.settimeout(5)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (f"GET {path} HTTP/1.1\r\n"
                   f"Host: {ws.hostname}:{ws.port or 9222}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response and len(response) < 16384:
            response += sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("DevTools WebSocket upgrade refused")
        expression = """(() => {
          const root = document.querySelector('[data-testid="fgb-broadcast"][data-target="youtube"]');
          return {root: !!root, url: location.href, ready: document.readyState,
                  layer: root?.getAttribute('data-layer') || '',
                  title: document.title, hidden: document.visibilityState};
        })()"""
        send_ws(sock, json.dumps({"id": 8301, "method": "Runtime.evaluate",
                                  "params": {"expression": expression, "returnByValue": True}}).encode())
        for _ in range(30):
            opcode, data = read_frame(sock)
            if opcode == 9:
                send_ws(sock, data, 10)
                continue
            if opcode == 8:
                raise RuntimeError("Renderer closed WebSocket")
            if opcode != 1:
                continue
            msg = json.loads(data.decode("utf-8"))
            if msg.get("method") == "Inspector.targetCrashed":
                raise RuntimeError("Chromium renderer crashed")
            if msg.get("id") == 8301:
                if msg.get("error"):
                    raise RuntimeError("Renderer did not accept inspection: " + str(msg["error"])[:120])
                result = msg.get("result", {})
                if result.get("exceptionDetails"):
                    raise RuntimeError("Renderer JS evaluation failed")
                return result.get("result", {}).get("value", {})
        raise RuntimeError("No renderer response")
    finally:
        sock.close()


def health(tab: dict) -> dict:
    try:
        data = eval_tab(tab)
        good = (data.get("root") is True
                and data.get("ready") in ("interactive", "complete")
                and data.get("url", "").startswith("https://epiccontentcreatorgrants.org/fgb-broadcast")
                and "target=youtube" in data.get("url", ""))
        return {"ok": good, "reason": "ok" if good else "broadcast_root_missing",
                "title": str(data.get("title", ""))[:100], "layer": str(data.get("layer", ""))[:50]}
    except Exception as error:
        return {"ok": False, "reason": type(error).__name__, "detail": str(error)[:130]}


def check_browser() -> dict:
    try:
        tabs = broadcast_tabs()
        if not tabs:
            return {"ok": False, "reason": "fgb_tab_missing"}
        # Any responding FGB tab is healthy; avoid treating stale or duplicate
        # historical tabs as an outage while a good replacement is active.
        probes = [(tab, health(tab)) for tab in tabs]
        for tab, result in probes:
            if result["ok"]:
                return {"target_id": tab.get("id"), "targets": len(tabs), **result}
        tab, result = probes[0]
        return {"target_id": tab.get("id"), "targets": len(tabs), **result}
    except Exception as error:
        return {"ok": False, "reason": "debug_endpoint_unavailable",
                "detail": str(error)[:130]}


def replace_tab() -> dict:
    # Never restart the browser process: the existing container owns Chromium.
    # A crashed renderer may replace its address with chrome-error://;
    # an empty FGB tab inventory must not block creation of a fresh FGB tab.
    old = broadcast_tabs()
    request_url = DEVTOOLS + "/json/new?" + quote(URL, safe="")
    try:
        fresh = get_json(request_url, method="PUT")
        if not isinstance(fresh, dict) or not fresh.get("id"):
            return {"ok": False, "reason": "new_target_failed"}
        new_id = str(fresh["id"])
        for _ in range(10):
            time.sleep(2)
            probe = health(fresh)
            if probe["ok"]:
                break
        else:
            return {"ok": False, "reason": "replacement_failed_health_check", "target_id": new_id}
        # Chrome's /json/activate and /json/close return plain text, not JSON.
        with urlopen(DEVTOOLS + "/json/activate/" + quote(new_id, safe=""), timeout=5) as resp:
            resp.read()
        time.sleep(3)
        again = health(fresh)
        if not again["ok"]:
            return {"ok": False, "reason": "replacement_failed_activation", "probe": again}
        closed = 0
        for previous in old:
            prior_id = str(previous.get("id", ""))
            if prior_id and prior_id != new_id:
                try:
                    with urlopen(DEVTOOLS + "/json/close/" + quote(prior_id, safe=""), timeout=5) as resp:
                        resp.read()
                    closed += 1
                except Exception:
                    pass
        return {"ok": True, "new_target_id": new_id, "closed_stale_targets": closed,
                "page_title": again.get("title")}
    except Exception as error:
        return {"ok": False, "reason": type(error).__name__, "detail": str(error)[:150]}


def inside_container() -> None:
    mode = sys.argv[1]
    data = check_browser() if mode == "--cdp-probe" else replace_tab()
    print(json.dumps(data), flush=True)
    if mode == "--cdp-replace" and not data.get("ok"):
        raise SystemExit(1)


def container_exec(mode: str, timeout: int = 28) -> dict:
    # No network, keys, or streaming credential is passed to Chromium.
    source = Path(__file__).read_text()
    proc = subprocess.run(["sudo", "-n", "docker", "exec", "-i", CONTAINER,
                           "python3", "-", mode], input=source, text=True,
                          capture_output=True, timeout=timeout)
    if not proc.stdout.strip():
        return {"ok": False, "reason": "docker_probe_failed", "detail": proc.stderr[-120:]}
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        if proc.returncode != 0:
            result["ok"] = False
        return result
    except Exception:
        return {"ok": False, "reason": "probe_json_invalid"}


def ffmpeg_pid() -> str:
    proc = subprocess.run(["sudo", "-n", "docker", "exec", CONTAINER,
                           "sh", "-c", "pgrep -o ffmpeg"], capture_output=True, text=True, timeout=6)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def live_state() -> str:
    proc = subprocess.run(["sudo", "-n", "docker", "exec", CONTAINER,
                           "sh", "-c", "cat /tmp/fgb-transport.state"], capture_output=True, text=True, timeout=6)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def host_main() -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("skipped", reason="prior_check_still_running")
            return
        now = int(time.time())
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            state = {}
        streak = int(state.get("failureStreak", 0))
        events = [int(t) for t in state.get("recoveries", []) if now - int(t) < 3600]
        probe = container_exec("--cdp-probe", 12)
        if probe.get("ok"):
            state = {"failureStreak": 0, "recoveries": events, "lastHealthyAt": now}
            emit("healthy", layer=probe.get("layer"), targets=probe.get("targets"))
        else:
            streak += 1
            state = {"failureStreak": streak, "recoveries": events, "lastFailureAt": now}
            emit("renderer_unhealthy", streak=streak, reason=probe.get("reason"),
                 detail=probe.get("detail", ""))
            if streak >= PROBE_FAIL_THRESHOLD:
                last = events[-1] if events else 0
                if len(events) >= RECOVERY_LIMIT_PER_HOUR or now - last < RECOVERY_COOLDOWN_SECONDS:
                    emit("recovery_suppressed", reason="cooldown_or_limit")
                elif live_state() != "live":
                    emit("recovery_suppressed", reason="encoder_not_live")
                else:
                    before = ffmpeg_pid()
                    if not before:
                        emit("recovery_suppressed", reason="ffmpeg_missing")
                    else:
                        # Account for attempts, even unsuccessful, to prevent restart storms.
                        events.append(now)
                        state["recoveries"] = events
                        response = container_exec("--cdp-replace", 38)
                        after = ffmpeg_pid()
                        source = live_state()
                        if before == after and source == "live" and response.get("ok"):
                            state["failureStreak"] = 0
                            emit("fgb_tab_recovered", encoder_preserved=True,
                                 old_tabs_closed=response.get("closed_stale_targets", 0))
                        else:
                            emit("recovery_incomplete", reason=response.get("reason"),
                                 encoder_preserved=bool(before == after and source == "live"))
        temp = STATE_FILE.with_suffix(".new")
        temp.write_text(json.dumps(state, sort_keys=True))
        os.chmod(temp, 0o600)
        temp.replace(STATE_FILE)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("--cdp-probe", "--cdp-replace"):
        inside_container()
    elif len(sys.argv) == 1:
        host_main()
    else:
        raise SystemExit("Only watchdog mode and fixed CDP subcommands are supported.")

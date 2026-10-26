#!/usr/bin/env python3
"""CNT-only CDP public game-screen fetch relay.

Chrome sometimes stalls on /api/public/fgbears/game-screen even when a curl -4
request from the same network namespace succeeds. This process intercepts only
that GET in the CNT capture tab and passes through the actual upstream response.
No cache, no fake questions, no FGB container access, no browser reload.
On upstream failure, the original browser request is allowed to continue.
"""
from __future__ import annotations
import base64
import concurrent.futures
import json
import os
import select
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

API = "https://epiccontentcreatorgrants.org/api/public/fgbears/game-screen"
PAGE = "https://epiccontentcreatorgrants.org/channels/cruisenewstrivia/broadcast"
CDP_LIST = "http://127.0.0.1:9223/json/list"

def log(message: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "CNT_FEED_RELAY", message, flush=True)

def get_actual_upstream() -> bytes:
    # Use CNT's own DNS/resolver, NOT the host resolv.conf carried into nsenter.
    # This route was confirmed HTTP 200 in 3/3 live origin probes on OVH.
    # Return exactly the public origin JSON with no stale-state fallback.
    last = "upstream timeout"
    for attempt in range(2):
        try:
            cp = subprocess.run(
                ["docker", "exec", "epic-cnt-capture", "curl", "-4",
                 "--fail", "--silent", "--show-error",
                 "--connect-timeout", "2", "--max-time", "5",
                 "-H", "Cache-Control: no-cache", API],
                capture_output=True, timeout=7, check=False)
            if cp.returncode != 0:
                last = f"HTTP_RETRIEVAL_FAILED_{cp.returncode}"
                continue
            body = cp.stdout
            if not (2 < len(body) < 130000):
                last = "BAD_BODY_SIZE"
                continue
            d = json.loads(body)
            if not isinstance(d, dict) or "phase" not in d:
                last = "INVALID_GAME_SCHEMA"
                continue
            return body
        except (subprocess.TimeoutExpired, ValueError):
            last = "UPSTREAM_TIMEOUT_OR_INVALID_JSON"
        if attempt == 0:
            time.sleep(0.4)
    raise RuntimeError(last)

class Socket:
    def __init__(self, url):
        ws = urllib.parse.urlsplit(url)
        self.sock = socket.create_connection((ws.hostname, ws.port), timeout=5)
        self.sock.settimeout(12)
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {ws.path} HTTP/1.1\r\n"
                           f"Host: {ws.hostname}:{ws.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            chunk = self.sock.recv(2048)
            if not chunk: raise RuntimeError("CDP handshake closed")
            buf += chunk
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError("CDP refused upgrade")
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self.cmd_id = 0

    def readn(self, n):
        while len(self.buf) < n:
            b = self.sock.recv(65536)
            if not b: raise ConnectionError("CDP disconnected")
            self.buf += b
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def send_raw(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        if n < 126: header = bytes([0x80 | opcode, 0x80 | n])
        elif n < 65536: header = bytes([0x80 | opcode, 0xfe]) + struct.pack("!H", n)
        else: header = bytes([0x80 | opcode, 0xff]) + struct.pack("!Q", n)
        self.sock.sendall(header + mask + bytes(x ^ mask[i % 4] for i, x in enumerate(data)))

    def command(self, method, params=None):
        self.cmd_id += 1
        self.send_raw(1, json.dumps({"id": self.cmd_id, "method": method, "params": params or {}},
                                    separators=(",", ":")).encode())

    def read(self):
        h = self.readn(2)
        opcode = h[0] & 15
        n = h[1] & 127
        if n == 126: n = struct.unpack("!H", self.readn(2))[0]
        elif n == 127: n = struct.unpack("!Q", self.readn(8))[0]
        if n > 2000000: raise RuntimeError("oversized CDP frame")
        mask = self.readn(4) if h[1] & 128 else None
        data = self.readn(n)
        if mask: data = bytes(x ^ mask[i % 4] for i, x in enumerate(data))
        if opcode == 9:
            self.send_raw(10, data)
            return None
        if opcode == 8: raise ConnectionError("CDP closed websocket")
        if opcode != 1: return None
        return json.loads(data)

def get_page():
    tabs = json.load(urllib.request.urlopen(CDP_LIST, timeout=4))
    pages = [p for p in tabs if p.get("type") == "page"]
    if len(pages) != 1 or pages[0].get("url") != PAGE:
        raise RuntimeError("CNT_PAGE_TARGET_MISMATCH_OR_NOT_UNIQUE")
    return pages[0]["webSocketDebuggerUrl"]

def main():
    url = get_page()
    socket_cdp = Socket(url)
    socket_cdp.command("Fetch.enable", {"patterns": [
        {"urlPattern": "*epiccontentcreatorgrants.org/api/public/fgbears/game-screen*",
         "resourceType": "Fetch", "requestStage": "Request"},
        {"urlPattern": "*epiccontentcreatorgrants.org/api/public/fgbears/game-screen*",
         "resourceType": "XHR", "requestStage": "Request"}
    ]})
    # A separate DevTools session may inspect or reload the CNT tab safely.
    log("BOUND_TO_CNT_TAB; CANONICAL_GAME_SOURCE; IPV4_RETRY; NO_CACHE")
    pending = {}
    summary = {"intercepted": 0, "fulfilled": 0, "fallback": 0}
    last_report = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        while True:
            for fut, reqid in list(pending.items()):
                if not fut.done(): continue
                pending.pop(fut)
                try:
                    body = fut.result()
                    socket_cdp.command("Fetch.fulfillRequest", {
                        "requestId": reqid, "responseCode": 200,
                        "responseHeaders": [
                            {"name": "Content-Type", "value": "application/json; charset=utf-8"},
                            {"name": "Cache-Control", "value": "no-store"}
                        ],
                        "body": base64.b64encode(body).decode("ascii")
                    })
                    summary["fulfilled"] += 1
                except Exception:
                    # Never create an invented or old question.
                    socket_cdp.command("Fetch.continueRequest", {"requestId": reqid})
                    summary["fallback"] += 1
            if time.monotonic() - last_report > 30:
                log("HEALTH " + json.dumps(summary, sort_keys=True))
                last_report = time.monotonic()
            if select.select([socket_cdp.sock], [], [], 0.35)[0]:
                message = socket_cdp.read()
                if not message or message.get("method") != "Fetch.requestPaused": continue
                request = message.get("params", {}).get("request") or {}
                reqid = message["params"]["requestId"]
                if (request.get("method", "").upper() != "GET"
                        or "/api/public/fgbears/game-screen" not in request.get("url", "")):
                    socket_cdp.command("Fetch.continueRequest", {"requestId": reqid})
                    continue
                summary["intercepted"] += 1
                # No more than two origin GETs in-flight at once.
                if len(pending) >= 2:
                    socket_cdp.command("Fetch.continueRequest", {"requestId": reqid})
                    summary["fallback"] += 1
                else:
                    pending[pool.submit(get_actual_upstream)] = reqid

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        log("EXIT " + type(exc).__name__ + ": " + str(exc)[:160])
        sys.exit(1)

#!/usr/bin/env python3
"""Health-check the CNT broadcast renderer, not merely the Chromium PID/port.

Runs INSIDE the CNT YouTube capture container; read-only Chromium DevTools
Protocol.  A tab title/PID check alone misses SIGTRAP/"Aw, Snap!" renderer
crashes while FFmpeg continues streaming X11 frames.
"""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request
import urllib.parse

CDP_URL = "http://127.0.0.1:9223/json/list"
CNT_URL_MARKER = "/channels/cruisenewstrivia/broadcast"
JS_PROBE = 'Boolean(document.getElementById("root") && document.getElementById("root").children.length) && !/Aw, Snap!|SIGTRAP|Error 1102/i.test((document.body && document.body.innerText || "").slice(0,500))'

def receive_exact(sock, size):
    data = b""
    while len(data) < size:
        piece = sock.recv(size - len(data))
        if not piece:
            raise OSError("WebSocket closed unexpectedly")
        data += piece
    return data

def read_ws(sock):
    b0, b1 = receive_exact(sock, 2)
    opcode = b0 & 0x0F
    length = b1 & 127
    if length == 126:
        length = struct.unpack("!H", receive_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", receive_exact(sock, 8))[0]
    mask = receive_exact(sock, 4) if b1 & 128 else b""
    payload = receive_exact(sock, length)
    if mask:
        payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
    if opcode == 8:
        raise OSError("DevTools target disconnected or crashed")
    return opcode, payload

def send_ws(sock, message):
    payload = json.dumps(message, separators=(",", ":")).encode()
    mask = os.urandom(4)
    if len(payload) < 126:
        header = bytes((0x81, 0x80 | len(payload)))
    elif len(payload) < 65536:
        header = bytes((0x81, 0xFE)) + struct.pack("!H", len(payload))
    else:
        raise ValueError("Unexpectedly large DevTools payload")
    body = bytes(ch ^ mask[i % 4] for i, ch in enumerate(payload))
    sock.sendall(header + mask + body)

def evaluate_in_target(websocket_url):
    parsed = urllib.parse.urlsplit(websocket_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9223
    path = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
    with socket.create_connection((host, port), timeout=4) as sock:
        sock.settimeout(4)
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += receive_exact(sock, 1)
            if len(head) > 8192:
                raise OSError("Invalid DevTools handshake")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError("DevTools WebSocket upgrade rejected")
        send_ws(sock, {
            "id": 1701,
            "method": "Runtime.evaluate",
            "params": {"expression": JS_PROBE, "returnByValue": True}
        })
        for _ in range(50):
            opcode, data = read_ws(sock)
            if opcode != 1:
                continue
            message = json.loads(data.decode("utf-8"))
            if message.get("method") in ("Inspector.targetCrashed", "Target.targetCrashed"):
                raise OSError("Renderer crash event")
            if message.get("id") != 1701:
                continue
            if message.get("error") or message.get("result", {}).get("exceptionDetails"):
                raise OSError("Renderer failed JavaScript evaluation")
            return message.get("result", {}).get("result", {}).get("value") is True
        raise TimeoutError("Renderer did not answer probe")

def main():
    with urllib.request.urlopen(CDP_URL, timeout=4) as response:
        targets = json.load(response)
    pages = [t for t in targets if t.get("type") == "page"
             and CNT_URL_MARKER in t.get("url", "")]
    if len(pages) != 1:
        raise ValueError("Expected exactly one CNT YouTube broadcast tab; found " + str(len(pages)))
    page = pages[0]
    if any(marker in page.get("title", "") for marker in ("Aw, Snap!", "SIGTRAP", "Cloudflare Error")):
        raise ValueError("Browser tab title indicates a crash or origin failure")
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        raise ValueError("Broadcast tab lacks a DevTools target")
    if not evaluate_in_target(ws_url):
        raise ValueError("CNT broadcast renderer did not return a healthy React page")
    print("CNT_RENDERER_HEALTH=OK")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("CNT_RENDERER_HEALTH=FAIL REASON=" + type(exc).__name__ + ":" + str(exc)[:200])
        sys.exit(2)

#!/usr/bin/env python3
"""Bounded loopback MPEG-TS delay relay for the YouTube-only path.

The shared master continues to publish its YouTube mirror to the existing
loopback UDP port. This process holds each datagram for a fixed, small playout
reserve before forwarding it to the YouTube compositor's private input port.
Rumble is not routed through this relay.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import select
import socket
import tempfile
import time
from urllib.parse import urlsplit

INGRESS_URL = os.getenv("YOUTUBE_LOCAL_UDP_URL", "udp://127.0.0.1:1939?pkt_size=1316")
OUTPUT_URL = os.getenv("YOUTUBE_V3_BUFFERED_UDP_URL", "udp://127.0.0.1:1941?pkt_size=1316")
BUFFER_SECONDS = float(os.getenv("YOUTUBE_V3_BUFFER_SECONDS", "4"))
MAX_QUEUE_BYTES = int(os.getenv("YOUTUBE_V3_BUFFER_MAX_BYTES", str(16 * 1024 * 1024)))
HEALTH_FILE = Path(os.getenv(
    "YOUTUBE_V3_BUFFER_HEALTH_FILE", "/run/fgbears-youtube-v3/delay-health.json"
))

if not 1.0 <= BUFFER_SECONDS <= 10.0:
    raise ValueError("YOUTUBE_V3_BUFFER_SECONDS must be between 1 and 10 seconds")
if MAX_QUEUE_BYTES < 1024 * 1024:
    raise ValueError("YOUTUBE_V3_BUFFER_MAX_BYTES must be at least 1 MiB")


def endpoint(url: str) -> tuple[str, int]:
    parsed = urlsplit(url)
    if parsed.scheme != "udp" or not parsed.hostname or not parsed.port:
        raise ValueError(f"invalid loopback UDP URL: {url}")
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("YouTube delay relay must stay on loopback")
    return "127.0.0.1", int(parsed.port)


def atomic_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def self_test() -> int:
    ingress = endpoint(INGRESS_URL)
    output = endpoint(OUTPUT_URL)
    assert ingress != output
    assert BUFFER_SECONDS == 4.0 or 1.0 <= BUFFER_SECONDS <= 10.0
    print(json.dumps({
        "ok": True,
        "bufferSeconds": BUFFER_SECONDS,
        "ingress": f"{ingress[0]}:{ingress[1]}",
        "output": f"{output[0]}:{output[1]}",
        "maxQueueBytes": MAX_QUEUE_BYTES,
        "protocol": "udp-mpegts-loopback",
    }, separators=(",", ":")))
    return 0


def run() -> int:
    ingress = endpoint(INGRESS_URL)
    output = endpoint(OUTPUT_URL)
    if ingress == output:
        raise ValueError("buffer ingress and output must use different ports")

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    receiver.bind(ingress)
    receiver.setblocking(False)

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)

    queue: deque[tuple[float, float, bytes]] = deque()
    queued_bytes = 0
    received = 0
    released = 0
    last_health = 0.0

    while True:
        now = time.monotonic()
        while queue and queue[0][0] <= now:
            _, _, payload = queue.popleft()
            sender.sendto(payload, output)
            queued_bytes -= len(payload)
            released += 1

        next_due = queue[0][0] if queue else now + 0.050
        timeout = max(0.0, min(0.050, next_due - now))
        readable, _, _ = select.select([receiver], [], [], timeout)
        if readable:
            while True:
                try:
                    payload, _ = receiver.recvfrom(65535)
                except BlockingIOError:
                    break
                arrival = time.monotonic()
                queue.append((arrival + BUFFER_SECONDS, arrival, payload))
                queued_bytes += len(payload)
                received += 1
                if queued_bytes > MAX_QUEUE_BYTES:
                    raise RuntimeError(
                        f"YouTube playout buffer exceeded {MAX_QUEUE_BYTES} bytes; refusing unbounded growth"
                    )

        now = time.monotonic()
        if now - last_health >= 1.0:
            oldest_age = max(0.0, now - queue[0][1]) if queue else 0.0
            newest_age = max(0.0, now - queue[-1][1]) if queue else 0.0
            depth = max(0.0, oldest_age - newest_age) if queue else 0.0
            atomic_json(HEALTH_FILE, {
                "ok": True,
                "bufferSeconds": BUFFER_SECONDS,
                "queuePackets": len(queue),
                "queueBytes": queued_bytes,
                "queueDepthSeconds": round(depth, 3),
                "oldestPacketAgeSeconds": round(oldest_age, 3),
                "receivedPackets": received,
                "releasedPackets": released,
                "ingressPort": ingress[1],
                "outputPort": output[1],
                "updatedAtEpoch": time.time(),
            })
            last_health = now


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return self_test() if args.self_test else run()


if __name__ == "__main__":
    raise SystemExit(main())

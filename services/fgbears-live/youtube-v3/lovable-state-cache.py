#!/usr/bin/env python3
"""FGB Lovable control-plane cache.

This process is the sole network client in the YouTube v3 presentation path.
It polls the one authoritative Lovable contract, validates it, and atomically
publishes last-known-good state to local disk. Invalid/unavailable responses
never replace last-known-good state. Consumers enforce validUntil themselves,
so an expired cache always fails transparent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.parse
import urllib.request

ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
STATE_FILE = Path(os.getenv(
    "FGB_CONTROL_STATE_FILE", "/run/fgbears-control-plane/stream-state.json"
))
HEALTH_FILE = Path(os.getenv(
    "FGB_CONTROL_HEALTH_FILE", "/run/fgbears-control-plane/cache-health.json"
))
POLL_SECONDS = float(os.getenv("FGB_CONTROL_POLL_SECONDS", "0.5"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("FGB_CONTROL_HTTP_TIMEOUT_SECONDS", "3.0"))
EXPECTED_SCHEMA = "fgb-stream-state/v1"
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"
EXPECTED_REGION = {
    "x": 462,
    "y": 104,
    "width": 798,
    "height": 470,
    "coordinateSpace": "pixels",
    "referenceWidth": 1280,
    "referenceHeight": 720,
}


def parse_timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return dt.timestamp()


def fetch() -> tuple[dict, float]:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "FGBears-Lovable-Control-Cache/1.0",
    })
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing payload is not an object")
    return payload, time.monotonic() - started


def validate(payload: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if payload.get("schemaVersion") != EXPECTED_SCHEMA:
        raise ValueError("unsupported schemaVersion")
    generated = parse_timestamp(payload.get("generatedAt"))
    valid_until = parse_timestamp(payload.get("validUntil"))
    if generated > now + 10:
        raise ValueError("generatedAt is implausibly in the future")
    if valid_until <= now:
        raise ValueError("contract already expired")
    if valid_until <= generated or valid_until - generated > 15:
        raise ValueError("invalid contract TTL")
    revision = payload.get("revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("missing revision")

    presentation = payload.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("missing presentation")
    ad_break = presentation.get("adBreak")
    trivia = presentation.get("trivia")
    routing = presentation.get("routing")
    overlay = presentation.get("overlay")
    if not all(isinstance(v, dict) for v in (ad_break, trivia, routing, overlay)):
        raise ValueError("incomplete presentation contract")
    for projected in ("crawl", "news", "schedule"):
        if not isinstance(presentation.get(projected), dict):
            raise ValueError(f"missing {projected} projection")
    if type(ad_break.get("active")) is not bool:
        raise ValueError("adBreak.active must be boolean")

    rumble = routing.get("rumble")
    youtube = routing.get("youtube")
    if not isinstance(rumble, dict) or not isinstance(youtube, dict):
        raise ValueError("missing destination routing")
    if rumble.get("rendersRealQuestion") is not True:
        raise ValueError("Rumble real-question invariant violated")
    difference = youtube.get("differenceLayer")
    if not isinstance(difference, dict) or type(difference.get("enabled")) is not bool:
        raise ValueError("missing YouTube differenceLayer decision")

    region = difference.get("region") or (presentation.get("mask") or {}).get("region")
    if not isinstance(region, dict):
        raise ValueError("missing mask region")
    for key, expected in EXPECTED_REGION.items():
        if region.get(key) != expected:
            raise ValueError(f"mask contract mismatch: {key}")

    if difference.get("enabled") is True:
        if difference.get("creativeKey") != EXPECTED_CREATIVE:
            raise ValueError("unknown active creative")
        if ad_break.get("active") is not False:
            raise ValueError("difference layer active during ad break")
        if str(trivia.get("phase") or "").strip().lower() != "question":
            raise ValueError("difference layer active outside question phase")
        if trivia.get("stale") is True:
            raise ValueError("difference layer active on stale trivia")
        if trivia.get("gameVisible") is not True:
            raise ValueError("difference layer active while game is hidden")
        if trivia.get("youtubeRedirectRequired") is not True:
            raise ValueError("difference layer lacks explicit Lovable requirement")

    return payload


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


def write_health(*, ok: bool, last_good: float, revision: str | None, latency: float | None, error: str | None) -> None:
    atomic_json(HEALTH_FILE, {
        "workerVersion": "lovable-control-cache-v1",
        "authority": "/api/public/fgbears/stream-routing",
        "schemaVersion": EXPECTED_SCHEMA,
        "ok": ok,
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lastGoodEpoch": last_good or None,
        "lastGoodAgeSeconds": max(0.0, time.time() - last_good) if last_good else None,
        "revision": revision,
        "routingLatencyMs": round(latency * 1000.0, 2) if latency is not None else None,
        "error": error,
    })


def run_once() -> tuple[dict, float]:
    payload, latency = fetch()
    return validate(payload), latency


def loop() -> int:
    last_good = 0.0
    last_revision: str | None = None
    last_latency: float | None = None
    deadline = time.monotonic()
    while True:
        try:
            payload, latency = run_once()
            atomic_json(STATE_FILE, payload)
            last_good = time.time()
            last_revision = str(payload["revision"])
            last_latency = latency
            write_health(ok=True, last_good=last_good, revision=last_revision, latency=latency, error=None)
        except Exception as exc:
            # Never replace LKG with invalid/unavailable state.
            write_health(
                ok=False,
                last_good=last_good,
                revision=last_revision,
                latency=last_latency,
                error=str(exc),
            )
            print(f"control-plane poll warning: {exc}", file=os.sys.stderr)
        deadline += POLL_SECONDS
        delay = deadline - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            deadline = time.monotonic()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        payload, latency = run_once()
        print(json.dumps({
            "ok": True,
            "schemaVersion": payload["schemaVersion"],
            "revision": payload["revision"],
            "routingLatencyMs": round(latency * 1000.0, 2),
        }, separators=(",", ":")))
        return 0
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())

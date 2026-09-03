#!/usr/bin/env python3
"""Network boundary for the FGB Lovable control plane.

This is the ONLY YouTube-v2 process that talks to Lovable. It polls the one
public stream-routing contract, validates its normalized envelope, and atomically
replaces the local last-known-good cache. Invalid/unavailable responses never
replace the cache. Media/render processes read only the local file and apply
validUntil themselves, so an old LKG automatically fails transparent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
CACHE_FILE = Path(os.getenv(
    "FGB_CONTROL_STATE_FILE", "/run/fgbears-control-plane/stream-state.json"
))
HEALTH_FILE = Path(os.getenv(
    "FGB_CONTROL_HEALTH_FILE", "/run/fgbears-control-plane/cache-health.json"
))
POLL_SECONDS = float(os.getenv("FGB_CONTROL_POLL_SECONDS", "0.5"))
TIMEOUT_SECONDS = float(os.getenv("FGB_CONTROL_HTTP_TIMEOUT_SECONDS", "1.5"))
EXPECTED_SCHEMA = "fgb-stream-state/v1"
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"
EXPECTED_REGION = {
    "x": 462, "y": 104, "width": 798, "height": 470,
    "coordinateSpace": "pixels", "referenceWidth": 1280, "referenceHeight": 720,
}


def parse_time(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt.timestamp()


def fetch() -> dict:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "FGBears-Lovable-Control-Cache/1.0",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing payload is not an object")
    return payload


def validate(payload: dict, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if payload.get("schemaVersion") != EXPECTED_SCHEMA:
        raise ValueError("unsupported schemaVersion")
    generated = parse_time(payload.get("generatedAt"))
    valid_until = parse_time(payload.get("validUntil"))
    if generated > now + 10:
        raise ValueError("generatedAt is implausibly in the future")
    if valid_until <= now:
        raise ValueError("contract already expired")
    if valid_until <= generated:
        raise ValueError("validUntil must be after generatedAt")
    if valid_until - generated > 30:
        raise ValueError("contract TTL exceeds 30 seconds")
    revision = payload.get("revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("missing revision")

    p = payload.get("presentation")
    if not isinstance(p, dict):
        raise ValueError("missing presentation")
    ad_break = p.get("adBreak")
    trivia = p.get("trivia")
    routing = p.get("routing")
    overlay = p.get("overlay")
    if not all(isinstance(x, dict) for x in (ad_break, trivia, routing, overlay)):
        raise ValueError("incomplete presentation contract")
    if not isinstance(p.get("crawl"), dict) or not isinstance(p.get("news"), dict) or not isinstance(p.get("schedule"), dict):
        raise ValueError("missing crawl/news/schedule projection")
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

    region = difference.get("region") or overlay.get("maskRegion")
    if not isinstance(region, dict):
        raise ValueError("missing difference-layer region")
    for key, expected in EXPECTED_REGION.items():
        if region.get(key) != expected:
            raise ValueError(f"mask contract mismatch: {key}")

    if difference.get("enabled") is True:
        if difference.get("creativeKey") != EXPECTED_CREATIVE:
            raise ValueError("unknown active creative")
        if ad_break.get("active") is True:
            raise ValueError("difference layer active during ad break")
        if str(trivia.get("phase") or "").lower() != "question":
            raise ValueError("difference layer active outside question phase")
        if trivia.get("stale") is True or trivia.get("fresh") is False:
            raise ValueError("difference layer active on stale trivia")
        if trivia.get("gameVisible") is not True:
            raise ValueError("difference layer active while game hidden")
        if trivia.get("youtubeRedirectRequired") is not True:
            raise ValueError("difference layer active without explicit Lovable requirement")

    return payload


def atomic_json(path: Path, body: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(body, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def write_health(*, ok: bool, last_good: float, error: str | None = None, revision: str | None = None) -> None:
    atomic_json(HEALTH_FILE, {
        "ok": ok,
        "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lastGoodEpoch": last_good or None,
        "lastGoodAgeSeconds": max(0.0, time.time() - last_good) if last_good else None,
        "revision": revision,
        "error": error,
        "authority": "lovable:/api/public/fgbears/stream-routing",
    })


def run_once() -> dict:
    return validate(fetch())


def loop() -> int:
    last_good = 0.0
    last_revision: str | None = None
    while True:
        started = time.monotonic()
        try:
            payload = run_once()
            atomic_json(CACHE_FILE, payload)
            last_good = time.time()
            last_revision = str(payload["revision"])
            write_health(ok=True, last_good=last_good, revision=last_revision)
        except Exception as exc:
            # Never replace LKG with invalid state. Consumer expiration is the
            # fail-transparent mechanism.
            write_health(ok=False, last_good=last_good, revision=last_revision, error=str(exc))
            print(f"control-plane poll warning: {exc}", file=sys.stderr)
        delay = POLL_SECONDS - (time.monotonic() - started)
        if delay > 0:
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.self_test or args.once:
        payload = run_once()
        print(json.dumps({"ok": True, "schemaVersion": payload["schemaVersion"], "revision": payload["revision"]}, separators=(",", ":")))
        return 0
    return loop()


if __name__ == "__main__":
    raise SystemExit(main())

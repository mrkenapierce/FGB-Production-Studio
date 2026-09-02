#!/usr/bin/env python3
"""Lovable-driven YouTube-only trivia presentation renderer.

Lovable's public stream-routing endpoint is the control plane. This worker does
not own platform routing decisions or source geometry: it consumes
`trivia.maskRegion`, `trivia.youtubeCreativeKey`, and `trivia.presentation`.

The Lovable mask region is validated as the authoritative question location and
the YouTube execution cover uses that exact question rectangle. News, crawl,
and unrelated middle-panel pixels remain live and untouched. When inactive,
the same question-box frame is fully transparent.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PIL import Image

SOURCE_CANVAS_WIDTH = 1280
SOURCE_CANVAS_HEIGHT = 720
SOURCE_NEWS_BOTTOM = 104   # news occupies y=0..103
SOURCE_CRAWL_TOP = 574     # crawl begins at y=574
OUTPUT_CANVAS_WIDTH = int(os.getenv("YOUTUBE_OUTPUT_CANVAS_WIDTH", str(SOURCE_CANVAS_WIDTH)))
OUTPUT_CANVAS_HEIGHT = int(os.getenv("YOUTUBE_OUTPUT_CANVAS_HEIGHT", str(SOURCE_CANVAS_HEIGHT)))
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"
PORT = int(os.getenv("YOUTUBE_QUESTION_MASK_PORT", "8791"))
FPS = max(1, min(30, int(os.getenv("YOUTUBE_QUESTION_MASK_FPS", "30"))))
POLL_SECONDS = max(1, int(os.getenv("YOUTUBE_QUESTION_MASK_POLL_SECONDS", "1")))
STALE_SECONDS = max(3, int(os.getenv("YOUTUBE_QUESTION_MASK_STALE_SECONDS", "30")))
INITIAL_CONTRACT_RETRIES = max(1, int(os.getenv("YOUTUBE_QUESTION_MASK_CONTRACT_RETRIES", "30")))
ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)
CARD_BUILDER = Path(
    os.getenv(
        "YOUTUBE_REDIRECT_CARD_BUILDER",
        "/opt/fgbears-live/tools/build-youtube-rumble-trivia-card.py",
    )
)

if OUTPUT_CANVAS_WIDTH <= 0 or OUTPUT_CANVAS_HEIGHT <= 0:
    raise ValueError("YouTube execution canvas dimensions must be positive")
if OUTPUT_CANVAS_WIDTH * SOURCE_CANVAS_HEIGHT != OUTPUT_CANVAS_HEIGHT * SOURCE_CANVAS_WIDTH:
    raise ValueError("YouTube execution canvas must preserve the 16:9 Lovable reference aspect ratio")


def scaled(value: int, source: int, output: int) -> int:
    return int(round(value * output / source))


@dataclass(frozen=True)
class Contract:
    source_x: int
    source_y: int
    source_width: int
    source_height: int
    x: int
    y: int
    width: int
    height: int
    creative_key: str

    def region(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    def source_region(self) -> dict[str, int]:
        return {
            "x": self.source_x,
            "y": self.source_y,
            "width": self.source_width,
            "height": self.source_height,
        }


def load_routing() -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-Lovable-Routing-Bridge/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing response is not an object")
    return payload


def parse_contract(payload: dict[str, Any]) -> Contract:
    trivia = payload.get("trivia")
    if not isinstance(trivia, dict):
        raise ValueError("missing trivia routing object")

    region = trivia.get("maskRegion")
    if not isinstance(region, dict):
        raise ValueError("missing trivia.maskRegion")
    if region.get("coordinateSpace") != "pixels":
        raise ValueError("maskRegion coordinateSpace must be pixels")
    if region.get("referenceWidth") != SOURCE_CANVAS_WIDTH or region.get("referenceHeight") != SOURCE_CANVAS_HEIGHT:
        raise ValueError("maskRegion reference canvas must be 1280x720")

    try:
        source_x = int(region["x"])
        source_y = int(region["y"])
        source_width = int(region["width"])
        source_height = int(region["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("maskRegion has invalid numeric geometry") from exc

    if source_width <= 0 or source_height <= 0 or source_x < 0 or source_y < 0:
        raise ValueError("maskRegion must be positive and inside the canvas")
    if source_x + source_width > SOURCE_CANVAS_WIDTH or source_y + source_height > SOURCE_CANVAS_HEIGHT:
        raise ValueError("maskRegion exceeds the 1280x720 canvas")
    if source_y < SOURCE_NEWS_BOTTOM or source_y + source_height > SOURCE_CRAWL_TOP:
        raise ValueError("maskRegion would overlap the always-live news or crawl bands")

    creative = trivia.get("youtubeCreativeKey")
    presentation = trivia.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("missing trivia.presentation")
    youtube = presentation.get("youtube")
    rumble = presentation.get("rumble")
    if not isinstance(youtube, dict) or not isinstance(rumble, dict):
        raise ValueError("missing platform presentation contract")

    if creative != EXPECTED_CREATIVE:
        raise ValueError(f"unsupported YouTube creative key: {creative!r}")
    if youtube.get("creativeKey") != creative or youtube.get("sourceTemplateKey") != creative:
        raise ValueError("YouTube presentation creative does not match youtubeCreativeKey")
    if youtube.get("presentationMode") != "full_creative_scaled":
        raise ValueError("YouTube presentationMode must be full_creative_scaled")
    if youtube.get("rendersRealQuestion") is not False:
        raise ValueError("YouTube presentation must not render the real question")
    if rumble.get("rendersRealQuestion") is not True:
        raise ValueError("Rumble presentation must retain the real question")

    masked = youtube.get("maskedRegion")
    expected_source = {
        "x": source_x,
        "y": source_y,
        "width": source_width,
        "height": source_height,
    }
    if not isinstance(masked, dict) or any(masked.get(k) != v for k, v in expected_source.items()):
        raise ValueError("YouTube presentation maskedRegion differs from trivia.maskRegion")

    # Execute exactly the Lovable-authoritative question rectangle. The news
    # above and crawl below remain live and unrelated middle-panel pixels remain
    # untouched. Geometry is proportionally mapped to the YouTube canvas.
    x = scaled(source_x, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)
    y = scaled(source_y, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    width = scaled(source_width, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)
    height = scaled(source_height, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    output_news_bottom = scaled(SOURCE_NEWS_BOTTOM, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    output_crawl_top = scaled(SOURCE_CRAWL_TOP, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    if width <= 0 or height <= 0 or x < 0 or y < output_news_bottom or y + height > output_crawl_top:
        raise ValueError("scaled maskRegion would overlap the always-live news or crawl bands")
    if x + width > OUTPUT_CANVAS_WIDTH or y + height > OUTPUT_CANVAS_HEIGHT:
        raise ValueError("scaled maskRegion exceeds the YouTube execution canvas")

    return Contract(
        source_x=source_x,
        source_y=source_y,
        source_width=source_width,
        source_height=source_height,
        x=x,
        y=y,
        width=width,
        height=height,
        creative_key=str(creative),
    )


def load_initial_contract() -> tuple[Contract, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(1, INITIAL_CONTRACT_RETRIES + 1):
        try:
            payload = load_routing()
            return parse_contract(payload), payload
        except Exception as exc:
            last_error = exc
            print(f"Lovable routing contract unavailable ({attempt}/{INITIAL_CONTRACT_RETRIES}): {exc}", file=sys.stderr)
            if attempt < INITIAL_CONTRACT_RETRIES:
                time.sleep(1)
    raise RuntimeError(f"unable to obtain valid Lovable routing contract: {last_error}")


def build_locked_creative(contract: Contract) -> bytes:
    if contract.creative_key != EXPECTED_CREATIVE:
        raise ValueError("unsupported creative")
    if not CARD_BUILDER.is_file():
        raise FileNotFoundError(f"locked creative builder not found: {CARD_BUILDER}")

    with tempfile.TemporaryDirectory(prefix="fgb-youtube-card-") as tmp:
        source_path = Path(tmp) / "locked-card.png"
        subprocess.run(
            [sys.executable, str(CARD_BUILDER), str(source_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        with Image.open(source_path) as raw:
            if raw.size != (SOURCE_CANVAS_WIDTH, SOURCE_CANVAS_HEIGHT):
                raise ValueError(f"locked creative must be 1280x720, got {raw.size}")
            source = raw.convert("RGBA")

    # Fit the approved full card inside the exact protected question box without
    # changing its internal layout. The remainder of the box is opaque navy.
    scaled_card = source.copy()
    scaled_card.thumbnail((contract.width, contract.height), Image.Resampling.LANCZOS)

    result = Image.new("RGBA", (contract.width, contract.height), (11, 22, 42, 255))
    px = (contract.width - scaled_card.width) // 2
    py = (contract.height - scaled_card.height) // 2
    result.paste(scaled_card, (px, py), scaled_card)
    return result.tobytes()


CONTRACT, INITIAL_PAYLOAD = load_initial_contract()
TRANSPARENT = Image.new("RGBA", (CONTRACT.width, CONTRACT.height), (0, 0, 0, 0)).tobytes()
ACTIVE = build_locked_creative(CONTRACT)


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = False
        self.phase: str | None = None
        self.last_good = 0.0
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        current = parse_contract(payload)
        if current != CONTRACT:
            raise ValueError(
                f"Lovable presentation contract changed from {CONTRACT} to {current}; renderer restart required"
            )
        trivia = payload.get("trivia") if isinstance(payload.get("trivia"), dict) else {}
        phase = str(trivia.get("phase") or "") or None
        remote_stale = trivia.get("stale") is True
        ads_visible = trivia.get("adsVisible") is True
        ad_break = trivia.get("isAdBreak") is True or trivia.get("adBreakActive") is True
        requested_active = (
            trivia.get("youtubeMaskActive") is True
            and phase == "question"
            and not remote_stale
            and not ads_visible
            and not ad_break
        )
        with self.lock:
            if ads_visible or ad_break or phase != "question":
                self.active = False
            elif requested_active:
                self.active = True
            elif self.active and phase == "question":
                # Once the cover appears, keep it latched through transient
                # routing-flag/staleness changes for the full question phase.
                self.active = True
            self.phase = phase
            self.last_good = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            # Do not flash the cover off on a transient API/network error.
            # snapshot() still applies the finite stale-age safety bound.
            self.last_error = str(exc)

    def snapshot(self) -> tuple[bool, str | None, float, str | None]:
        with self.lock:
            age = time.time() - self.last_good if self.last_good else float("inf")
            return bool(self.active and age <= STALE_SECONDS), self.phase, age, self.last_error


STATE = State()
STATE.update(INITIAL_PAYLOAD)


def poll() -> None:
    while True:
        try:
            STATE.update(load_routing())
        except Exception as exc:
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def frame() -> bytes:
    active, _phase, _age, _error = STATE.snapshot()
    return ACTIVE if active else TRANSPARENT


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsLovableRoutingBridge/5.0"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            active, phase, age, error = STATE.snapshot()
            body = json.dumps({
                "ok": True,
                "active": active,
                "phase": phase,
                "lastGoodAgeSeconds": None if age == float("inf") else round(age, 3),
                "lastError": error,
                "sourceCanvas": [SOURCE_CANVAS_WIDTH, SOURCE_CANVAS_HEIGHT],
                "canvas": [OUTPUT_CANVAS_WIDTH, OUTPUT_CANVAS_HEIGHT],
                "sourceMaskRegion": CONTRACT.source_region(),
                "maskRegion": CONTRACT.region(),
                "frameSize": [CONTRACT.width, CONTRACT.height],
                "creativeKey": CONTRACT.creative_key,
                "presentationMode": "full_creative_scaled",
                "routingAuthority": "lovable_public_stream_routing",
                "executionScaling": "proportional_downstream",
                "fps": FPS,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/overlay.rgba"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        interval = 1.0 / FPS
        deadline = time.monotonic()
        try:
            while True:
                self.wfile.write(frame())
                self.wfile.flush()
                deadline += interval
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -interval:
                    deadline = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    threading.Thread(target=poll, daemon=True, name="lovable-routing-poller").start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

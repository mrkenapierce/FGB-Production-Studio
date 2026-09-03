#!/usr/bin/env python3
"""YouTube-only trivia concealment renderer controlled by Lovable routing.

The renderer validates Lovable's exact 1280x720 question rectangle and emits a
static RGBA replacement only for that rectangle. News, crawl, and all other
program pixels remain untouched. Concealment is deliberately fail-closed once
a question signal is present.
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
SOURCE_NEWS_BOTTOM = 104
SOURCE_CRAWL_TOP = 574
OUTPUT_CANVAS_WIDTH = int(os.getenv("YOUTUBE_OUTPUT_CANVAS_WIDTH", str(SOURCE_CANVAS_WIDTH)))
OUTPUT_CANVAS_HEIGHT = int(os.getenv("YOUTUBE_OUTPUT_CANVAS_HEIGHT", str(SOURCE_CANVAS_HEIGHT)))
EXPECTED_CREATIVE = "yt_rumble_trivia_redirect"
PORT = int(os.getenv("YOUTUBE_QUESTION_MASK_PORT", "8791"))
FPS = max(1, min(30, int(os.getenv("YOUTUBE_QUESTION_MASK_FPS", "15"))))
POLL_SECONDS = max(0.10, min(1.0, float(os.getenv("YOUTUBE_QUESTION_MASK_POLL_SECONDS", "0.20"))))
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
    raise ValueError("YouTube execution canvas must preserve 16:9")


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
            "User-Agent": "FGBears-Lovable-Routing-Bridge/5.3",
        },
    )
    with urllib.request.urlopen(req, timeout=2.0) as response:
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
        raise ValueError("maskRegion has invalid geometry") from exc

    if source_width <= 0 or source_height <= 0 or source_x < 0 or source_y < 0:
        raise ValueError("maskRegion must be positive")
    if source_x + source_width > SOURCE_CANVAS_WIDTH or source_y + source_height > SOURCE_CANVAS_HEIGHT:
        raise ValueError("maskRegion exceeds source canvas")
    if source_y < SOURCE_NEWS_BOTTOM or source_y + source_height > SOURCE_CRAWL_TOP:
        raise ValueError("maskRegion overlaps news or crawl")

    creative = trivia.get("youtubeCreativeKey")
    presentation = trivia.get("presentation")
    if not isinstance(presentation, dict):
        raise ValueError("missing trivia.presentation")
    youtube = presentation.get("youtube")
    rumble = presentation.get("rumble")
    if not isinstance(youtube, dict) or not isinstance(rumble, dict):
        raise ValueError("missing platform presentation contract")
    if creative != EXPECTED_CREATIVE:
        raise ValueError(f"unsupported creative key: {creative!r}")
    if youtube.get("creativeKey") != creative or youtube.get("sourceTemplateKey") != creative:
        raise ValueError("YouTube creative contract mismatch")
    if youtube.get("presentationMode") != "full_creative_scaled":
        raise ValueError("unexpected YouTube presentation mode")
    if youtube.get("rendersRealQuestion") is not False or rumble.get("rendersRealQuestion") is not True:
        raise ValueError("platform question-rendering contract mismatch")

    masked = youtube.get("maskedRegion")
    expected_source = {"x": source_x, "y": source_y, "width": source_width, "height": source_height}
    if not isinstance(masked, dict) or any(masked.get(k) != v for k, v in expected_source.items()):
        raise ValueError("YouTube maskedRegion differs from trivia.maskRegion")

    x = scaled(source_x, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)
    y = scaled(source_y, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    width = scaled(source_width, SOURCE_CANVAS_WIDTH, OUTPUT_CANVAS_WIDTH)
    height = scaled(source_height, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    news_bottom = scaled(SOURCE_NEWS_BOTTOM, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    crawl_top = scaled(SOURCE_CRAWL_TOP, SOURCE_CANVAS_HEIGHT, OUTPUT_CANVAS_HEIGHT)
    if width <= 0 or height <= 0 or x < 0 or y < news_bottom or y + height > crawl_top:
        raise ValueError("scaled mask overlaps protected bands")
    if x + width > OUTPUT_CANVAS_WIDTH or y + height > OUTPUT_CANVAS_HEIGHT:
        raise ValueError("scaled mask exceeds output canvas")

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
            print(f"Lovable routing unavailable ({attempt}/{INITIAL_CONTRACT_RETRIES}): {exc}", file=sys.stderr)
            if attempt < INITIAL_CONTRACT_RETRIES:
                time.sleep(1)
    raise RuntimeError(f"unable to obtain valid routing contract: {last_error}")


def build_locked_creative(contract: Contract) -> bytes:
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

    card = source.copy()
    card.thumbnail((contract.width, contract.height), Image.Resampling.LANCZOS)
    result = Image.new("RGBA", (contract.width, contract.height), (11, 22, 42, 255))
    result.paste(card, ((contract.width - card.width) // 2, (contract.height - card.height) // 2), card)
    return result.tobytes()


CONTRACT, INITIAL_PAYLOAD = load_initial_contract()
TRANSPARENT = Image.new("RGBA", (CONTRACT.width, CONTRACT.height), (0, 0, 0, 0)).tobytes()
ACTIVE = build_locked_creative(CONTRACT)


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = False
        self.phase: str | None = None
        self.question_active = False
        self.mask_active = False
        self.prearmed = False
        self.last_good = 0.0
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        current = parse_contract(payload)
        if current != CONTRACT:
            raise ValueError(f"presentation contract changed from {CONTRACT} to {current}; restart required")

        trivia = payload.get("trivia") if isinstance(payload.get("trivia"), dict) else {}
        phase = str(trivia.get("phase") or "") or None
        question_active = trivia.get("questionActive") is True
        mask_active = trivia.get("youtubeMaskActive") is True
        ads_visible = trivia.get("adsVisible") is True
        ad_break = trivia.get("isAdBreak") is True or trivia.get("adBreakActive") is True
        session_active = trivia.get("active") is True

        # Direct question signals win. During the clean transition after an ad
        # break, pre-arm the cover before the next question pixels are painted.
        prearmed = bool(session_active and phase == "transition" and not ads_visible and not ad_break)
        should_cover = bool(phase == "question" or question_active or mask_active or prearmed)

        with self.lock:
            self.active = should_cover
            self.phase = phase
            self.question_active = question_active
            self.mask_active = mask_active
            self.prearmed = prearmed
            self.last_good = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            # Preserve the last valid state. If the cover is up, a control-plane
            # timeout can never expose a live question.
            self.last_error = str(exc)

    def snapshot(self) -> tuple[bool, str | None, float, str | None, bool, bool, bool]:
        with self.lock:
            age = time.time() - self.last_good if self.last_good else float("inf")
            return (
                self.active,
                self.phase,
                age,
                self.last_error,
                self.question_active,
                self.mask_active,
                self.prearmed,
            )


STATE = State()
STATE.update(INITIAL_PAYLOAD)


def poll() -> None:
    while True:
        started = time.monotonic()
        try:
            STATE.update(load_routing())
        except Exception as exc:
            STATE.error(exc)
        delay = POLL_SECONDS - (time.monotonic() - started)
        if delay > 0:
            time.sleep(delay)


def frame() -> bytes:
    active, *_ = STATE.snapshot()
    return ACTIVE if active else TRANSPARENT


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsLovableRoutingBridge/5.3"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            active, phase, age, error, question_active, mask_active, prearmed = STATE.snapshot()
            body = json.dumps(
                {
                    "ok": True,
                    "active": active,
                    "phase": phase,
                    "questionActiveSignal": question_active,
                    "youtubeMaskActiveSignal": mask_active,
                    "prearmed": prearmed,
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
                    "failClosedDuringQuestion": True,
                    "pollSeconds": POLL_SECONDS,
                    "fps": FPS,
                }
            ).encode()
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

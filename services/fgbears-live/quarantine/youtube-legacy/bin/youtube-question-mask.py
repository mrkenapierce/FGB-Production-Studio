#!/usr/bin/env python3
"""YouTube-only partial trivia mask renderer.

This service never owns the source stream. It polls the authoritative public
stream-routing control plane and emits a transparent RGBA stream unless
`trivia.youtubeMaskActive` is explicitly true during a fresh `question` phase.

Critically, this renderer emits ONLY the question/answer rectangle, not a
1280x720 canvas. The off-host compositor anchors this 640x360 RGBA stream at
x=480, y=200 on the 1280x720 program. That physical size constraint prevents a
renderer failure from covering the full YouTube frame. The title, prize/countdown,
play QR, upper-third news, crawl, and ad regions remain outside this input.

Any routing error, stale state, malformed response, or missing explicit mask
signal fails transparent.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
MASK_X = int(os.getenv("YOUTUBE_QUESTION_MASK_X", "480"))
MASK_Y = int(os.getenv("YOUTUBE_QUESTION_MASK_Y", "200"))
MASK_WIDTH = int(os.getenv("YOUTUBE_QUESTION_MASK_WIDTH", "640"))
MASK_HEIGHT = int(os.getenv("YOUTUBE_QUESTION_MASK_HEIGHT", "360"))
PORT = int(os.getenv("YOUTUBE_QUESTION_MASK_PORT", "8791"))
FPS = max(1, min(30, int(os.getenv("YOUTUBE_QUESTION_MASK_FPS", "30"))))
POLL_SECONDS = max(1, int(os.getenv("YOUTUBE_QUESTION_MASK_POLL_SECONDS", "1")))
STALE_SECONDS = max(3, int(os.getenv("YOUTUBE_QUESTION_MASK_STALE_SECONDS", "8")))
ROUTING_URL = os.getenv(
    "FGB_STREAM_ROUTING_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/stream-routing",
)

if MASK_WIDTH <= 0 or MASK_HEIGHT <= 0:
    raise ValueError("question mask dimensions must be positive")
if MASK_X < 0 or MASK_Y < 0 or MASK_X + MASK_WIDTH > CANVAS_WIDTH or MASK_Y + MASK_HEIGHT > CANVAS_HEIGHT:
    raise ValueError("question mask must stay inside the 1280x720 program canvas")

BEARS_BLUE = "#0B162A"
DEEP_BLUE = "#07101F"
BEARS_ORANGE = "#C83803"
WHITE = "#FFFFFF"
MUTED = "#D5D9E2"
GOLD = "#F2B134"
FONT_REGULAR = os.getenv("YOUTUBE_QUESTION_MASK_FONT_REGULAR", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = os.getenv("YOUTUBE_QUESTION_MASK_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size=size)
    except OSError:
        return ImageFont.load_default()


def load_routing() -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(ROUTING_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": "FGBears-YouTube-Question-Mask/2.0",
    })
    with urllib.request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("routing response is not an object")
    return payload


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = False
        self.phase: str | None = None
        self.last_good = 0.0
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        trivia = payload.get("trivia") if isinstance(payload.get("trivia"), dict) else {}
        phase = str(trivia.get("phase") or "") or None
        remote_stale = trivia.get("stale") is True
        active = trivia.get("youtubeMaskActive") is True and phase == "question" and not remote_stale
        with self.lock:
            self.active = active
            self.phase = phase
            self.last_good = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.active = False
            self.last_error = str(exc)

    def snapshot(self) -> tuple[bool, str | None, float, str | None]:
        with self.lock:
            age = time.time() - self.last_good if self.last_good else float("inf")
            return bool(self.active and age <= STALE_SECONDS), self.phase, age, self.last_error


STATE = State()


def poll() -> None:
    while True:
        try:
            STATE.update(load_routing())
        except Exception as exc:
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def centered_x(draw: ImageDraw.ImageDraw, text: str, text_font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=text_font)
    return max(8, (MASK_WIDTH - (box[2] - box[0])) // 2)


def build_active_frame() -> bytes:
    image = Image.new("RGBA", (MASK_WIDTH, MASK_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (2, 2, MASK_WIDTH - 3, MASK_HEIGHT - 3),
        radius=16,
        fill=DEEP_BLUE,
        outline=BEARS_ORANGE,
        width=5,
    )
    title = "PLAY THIS QUESTION ON RUMBLE"
    title_font = font(31, bold=True)
    draw.text((centered_x(draw, title, title_font), 104), title, font=title_font, fill=WHITE)

    sub = "The live question and answer are available on Rumble."
    sub_font = font(21)
    draw.text((centered_x(draw, sub, sub_font), 164), sub, font=sub_font, fill=MUTED)

    note = "News, prizes and the crawl remain visible on YouTube."
    note_font = font(17)
    draw.text((centered_x(draw, note, note_font), 212), note, font=note_font, fill=GOLD)
    return image.tobytes()


TRANSPARENT = Image.new("RGBA", (MASK_WIDTH, MASK_HEIGHT), (0, 0, 0, 0)).tobytes()
ACTIVE = build_active_frame()


def frame() -> bytes:
    active, _phase, _age, _error = STATE.snapshot()
    return ACTIVE if active else TRANSPARENT


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsYouTubeQuestionMask/2.0"

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
                "canvas": [CANVAS_WIDTH, CANVAS_HEIGHT],
                "maskRegion": {"x": MASK_X, "y": MASK_Y, "width": MASK_WIDTH, "height": MASK_HEIGHT},
                "frameSize": [MASK_WIDTH, MASK_HEIGHT],
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
    try:
        STATE.update(load_routing())
    except Exception as exc:
        STATE.error(exc)
    threading.Thread(target=poll, daemon=True, name="routing-poller").start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

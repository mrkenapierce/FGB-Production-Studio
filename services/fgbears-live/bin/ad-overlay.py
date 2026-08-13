#!/usr/bin/env python3
"""Dynamic FGBears full-screen advertising interstitial.

Polls the public Lovable sponsor feed and serves a 1280x720 MJPEG creative that
FFmpeg displays as a timed, full-screen interstitial in the live broadcast.
The feed already applies paid-ad -> House Ad -> placeholder priority.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

FEED_URL = os.getenv(
    "SPONSOR_FEED_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/sponsors",
)
FEED_FILE = os.getenv("SPONSOR_FEED_FILE", "").strip()
POLL_SECONDS = max(5, int(os.getenv("SPONSOR_POLL_SECONDS", "10")))
ROTATION_SECONDS = max(5, int(os.getenv("AD_ROTATION_SECONDS", "20")))
PORT = int(os.getenv("AD_OVERLAY_PORT", "8787"))
WIDTH = 1280
HEIGHT = 720
# FFmpeg's multipart JPEG demuxer timestamps this input at 25 fps. Feeding it
# slower makes the complete broadcast timeline run behind real time.
FPS = 25

BEARS_BLUE = "#0B162A"
BEARS_ORANGE = "#C83803"
WHITE = "#FFFFFF"
MUTED = "#D5D9E2"
GOLD = "#F2B134"
EPIC_MEDIA_URL = "https://epiccontentcreatorgrants.org/epic-media"

FONT_REGULAR = os.getenv("AD_FONT_REGULAR", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = os.getenv("AD_FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
EPIC_LOGO_PATH = os.getenv("EPIC_LOGO_PATH", "/opt/fgbears-live/assets/epic-logo.png")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 14) -> ImageFont.ImageFont:
    size = start_size
    while size > min_size:
        f = font(size, bold=True)
        if draw.textbbox((0, 0), text, font=f)[2] <= max_width:
            return f
        size -= 2
    return font(min_size, bold=True)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textbbox((0, 0), trial, font=f)[2] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break
    if len(lines) < max_lines:
        remaining_start = sum(len(line.split()) for line in lines)
        remaining = words[remaining_start:]
        if remaining:
            current = " ".join(remaining)
            while draw.textbbox((0, 0), current, font=f)[2] > max_width and " " in current:
                parts = current.split()
                parts.pop()
                current = " ".join(parts)
            if len(current.split()) < len(remaining):
                current = current.rstrip(" .") + "…"
            lines.append(current)
    return lines[:max_lines]


class SponsorState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.kind = "placeholder"
        self.placeholder = "Your Ad Here"
        self.sponsors: list[dict[str, Any]] = []
        self.last_good_refresh = 0.0
        self.last_error: str | None = None
        self._image_cache: dict[str, Image.Image] = {}

    def update(self, payload: dict[str, Any]) -> None:
        sponsors = payload.get("sponsors")
        if not isinstance(sponsors, list):
            raise ValueError("feed payload is missing sponsors[]")
        with self._lock:
            self.kind = str(payload.get("kind") or ("placeholder" if not sponsors else "paid"))
            self.placeholder = str(payload.get("placeholder") or "Your Ad Here")
            self.sponsors = [s for s in sponsors if isinstance(s, dict)]
            self.last_good_refresh = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self._lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[str, str, list[dict[str, Any]], float, str | None]:
        with self._lock:
            return self.kind, self.placeholder, list(self.sponsors), self.last_good_refresh, self.last_error

    def image_for(self, url: str) -> Image.Image | None:
        if not url:
            return None
        with self._lock:
            cached = self._image_cache.get(url)
            if cached is not None:
                return cached.copy()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FGBears-Live/1.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                data = response.read(4_000_000)
            image = Image.open(io.BytesIO(data)).convert("RGBA")
            with self._lock:
                self._image_cache[url] = image.copy()
                if len(self._image_cache) > 20:
                    self._image_cache.pop(next(iter(self._image_cache)))
            return image
        except Exception:
            return None


STATE = SponsorState()
FRAME_CACHE_LOCK = threading.Lock()
FRAME_CACHE_KEY: tuple[float, int] | None = None
FRAME_CACHE_BYTES = b""


def load_feed_payload() -> dict[str, Any]:
    if FEED_FILE:
        return json.loads(Path(FEED_FILE).read_text(encoding="utf-8"))
    parsed = urllib.parse.urlsplit(FEED_URL)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(int(time.time()))))
    url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-Live/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"sponsor feed returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def poll_feed() -> None:
    while True:
        try:
            STATE.update(load_feed_payload())
        except Exception as exc:
            # Keep the last good ad during a transient network failure.
            STATE.error(exc)
        time.sleep(POLL_SECONDS)


def draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int, f: ImageFont.ImageFont, fill: str) -> int:
    bbox = draw.textbbox((0, 0), text, font=f)
    width = bbox[2] - bbox[0]
    draw.text(((WIDTH - width) / 2, y), text, font=f, fill=fill)
    return bbox[3] - bbox[1]


def draw_brand_frame(draw: ImageDraw.ImageDraw) -> None:
    """Draw the locked three-part FGBears full-screen frame."""
    draw.rectangle((0, 0, WIDTH, 96), fill=BEARS_ORANGE)
    draw.rectangle((0, HEIGHT - 82, WIDTH, HEIGHT), fill="#07101F")
    draw.rectangle((462, 97, WIDTH - 20, HEIGHT - 83), fill=WHITE)
    title = "FOOTBALL'S GREATEST BEARS LIVE"
    title_font = font(38, bold=True)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    draw.text(((WIDTH - (title_box[2] - title_box[0])) / 2, 24), title, font=title_font, fill=WHITE)
    draw.line((458, 116, 458, HEIGHT - 102), fill=BEARS_ORANGE, width=4)
    draw.text((112, HEIGHT - 56), "EPIC CONTENT CREATOR GRANTS", font=font(24, bold=True), fill=GOLD)
    draw.text((WIDTH - 430, HEIGHT - 54), "WE TURN CONTENT INTO OPPORTUNITY.", font=font(18, bold=True), fill=MUTED)
    draw.rectangle((18, 18, WIDTH - 19, HEIGHT - 19), outline=BEARS_ORANGE, width=4)


def draw_epic_media_qr(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Render the fixed left-middle QR panel for EPIC Media."""
    qr_size = 300
    qr = qr_for(EPIC_MEDIA_URL, qr_size)
    qr_x, qr_y = 80, 145
    if qr is not None:
        draw.rounded_rectangle((qr_x - 16, qr_y - 16, qr_x + qr_size + 16, qr_y + qr_size + 100), radius=20, fill=WHITE)
        image.paste(qr, (qr_x, qr_y))
        cta = "SCAN FOR EPIC MEDIA"
        cta_font = font(22, bold=True)
        cta_box = draw.textbbox((0, 0), cta, font=cta_font)
        draw.text((qr_x + (qr_size - (cta_box[2] - cta_box[0])) / 2, qr_y + qr_size + 22), cta, font=cta_font, fill=BEARS_BLUE)
        url = "epiccontentcreatorgrants.org/epic-media"
        url_font = fit_text(draw, url, qr_size - 16, 16, 12)
        url_box = draw.textbbox((0, 0), url, font=url_font)
        draw.text((qr_x + (qr_size - (url_box[2] - url_box[0])) / 2, qr_y + qr_size + 60), url, font=url_font, fill=BEARS_ORANGE)


def add_epic_logo(image: Image.Image) -> None:
    try:
        logo = Image.open(EPIC_LOGO_PATH).convert("RGBA")
        logo.thumbnail((56, 56), Image.Resampling.LANCZOS)
        image.paste(logo, (48, HEIGHT - 69), logo)
    except Exception:
        # The wordmark remains present if a deployment lacks the optional asset.
        return


def qr_for(url: str, size: int) -> Image.Image | None:
    if not url:
        return None
    try:
        encoded = subprocess.run(
            ["qrencode", "-t", "PNG", "-o", "-", "-s", "10", "-m", "4", url],
            check=True,
            capture_output=True,
            timeout=5,
        ).stdout
        return Image.open(io.BytesIO(encoded)).convert("RGB").resize((size, size), Image.Resampling.NEAREST)
    except Exception:
        return None


def house_event_parts(title: str) -> tuple[str, str]:
    """Split titles like 'Preseason Game One is 8/15/2026' for TV hierarchy."""
    match = re.fullmatch(r"\s*(.*?)\s+is\s+(\d{1,2})/(\d{1,2})/(\d{4})\s*", title, flags=re.IGNORECASE)
    if not match:
        return title, ""
    headline, month, day, year = match.groups()
    months = ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
    month_number = int(month)
    if not 1 <= month_number <= 12:
        return title, ""
    return headline, f"{months[month_number]} {int(day)}, {year}"


def render_placeholder(label: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BEARS_BLUE)
    draw = ImageDraw.Draw(image)
    draw_brand_frame(draw)
    draw_epic_media_qr(image, draw)
    draw.text((505, 128), "ADVERTISEMENT", font=font(21, bold=True), fill=BEARS_ORANGE)
    title = fit_text(draw, label.upper(), 710, 74, 42)
    draw.text((505, 225), label.upper(), font=title, fill=BEARS_ORANGE)
    draw.text((505, 340), "Promote your business during the live broadcast", font=font(29), fill=BEARS_BLUE)
    draw.text((505, 430), "epiccontentcreatorgrants.org/advertise/fgbears", font=font(24, bold=True), fill=BEARS_BLUE)
    add_epic_logo(image)
    return image


def render_sponsor(sponsor: dict[str, Any]) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BEARS_BLUE)
    draw = ImageDraw.Draw(image)

    business = str(sponsor.get("businessName") or "Advertisement").strip()
    message = str(sponsor.get("promoMessage") or "").strip()
    website = str(sponsor.get("website") or "").strip()
    image_url = str(sponsor.get("imageUrl") or "").strip()
    creative = STATE.image_for(image_url) if image_url else None
    kind = STATE.snapshot()[0]
    draw_brand_frame(draw)
    draw_epic_media_qr(image, draw)
    draw.text((505, 112), "ADVERTISEMENT", font=font(20, bold=True), fill=BEARS_ORANGE)

    if creative is not None:
        box = (505, 145, WIDTH - 48, 390)
        target_w = box[2] - box[0]
        target_h = box[3] - box[1]
        fitted = ImageOps.contain(creative, (target_w, target_h))
        canvas = Image.new("RGBA", (target_w, target_h), WHITE)
        canvas.alpha_composite(fitted, ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2))
        image.paste(canvas.convert("RGB"), (box[0], box[1]))
        text_x = 505
        text_w = WIDTH - text_x - 60
        headline, event_date = house_event_parts(business) if kind == "house" else (business, "")
        title_font = fit_text(draw, headline.upper(), text_w, 42, 27)
        title_lines = wrap_text(draw, headline.upper(), title_font, text_w, max_lines=2)
        y = 408
        for line in title_lines:
            draw.text((text_x, y), line, font=title_font, fill=BEARS_BLUE)
            y += int(getattr(title_font, "size", 34) * 1.12)
        if event_date:
            y += 2
            draw.text((text_x, y), event_date, font=font(28, bold=True), fill=BEARS_ORANGE)
            y += 39
        if message:
            msg_font = font(25, bold=True)
            y += 8
            for line in wrap_text(draw, message, msg_font, text_w, max_lines=2):
                draw.text((text_x, y), line.upper(), font=msg_font, fill=BEARS_ORANGE)
                y += 32
        if website:
            parsed = urllib.parse.urlsplit(website)
            site = parsed.netloc + parsed.path
            site_font = fit_text(draw, site, text_w, 20, 15)
            draw.text((text_x, HEIGHT - 125), site, font=site_font, fill=BEARS_BLUE)
        add_epic_logo(image)
        return image

    # Text-only ads become complete broadcast creatives rather than sparse cards.
    text_x = 505
    text_w = WIDTH - text_x - 60
    headline, event_date = house_event_parts(business) if kind == "house" else (business, "")
    title_font = fit_text(draw, headline.upper(), text_w, 66, 38)
    title_lines = wrap_text(draw, headline.upper(), title_font, text_w, max_lines=3)
    line_h = int(getattr(title_font, "size", 52) * 1.12)
    y = 190
    for line in title_lines:
        draw.text((text_x, y), line, font=title_font, fill=BEARS_BLUE)
        y += line_h

    if event_date:
        y += 12
        draw.text((text_x, y), event_date, font=font(38, bold=True), fill=BEARS_ORANGE)
        y += 66

    if message:
        msg_font = font(38, bold=True)
        y += 18
        for line in wrap_text(draw, message, msg_font, text_w, max_lines=3):
            draw.text((text_x, y), line.upper(), font=msg_font, fill=BEARS_ORANGE)
            y += 48

    if website:
        displayed_url = website
        site = urllib.parse.urlsplit(displayed_url).netloc + urllib.parse.urlsplit(displayed_url).path if displayed_url else ""
        site_font = fit_text(draw, site, text_w, 24, 17)
        draw.text((text_x, HEIGHT - 130), site, font=site_font, fill=BEARS_BLUE)
    add_epic_logo(image)
    return image


def current_frame() -> Image.Image:
    _kind, placeholder, sponsors, _refreshed, _error = STATE.snapshot()
    if not sponsors:
        return render_placeholder(placeholder)
    index = int(time.time() // ROTATION_SECONDS) % len(sponsors)
    return render_sponsor(sponsors[index])


def jpeg_bytes() -> bytes:
    global FRAME_CACHE_BYTES, FRAME_CACHE_KEY
    _kind, _placeholder, sponsors, refreshed, _error = STATE.snapshot()
    rotation = int(time.time() // ROTATION_SECONDS) if len(sponsors) > 1 else 0
    key = (refreshed, rotation)
    with FRAME_CACHE_LOCK:
        if FRAME_CACHE_KEY == key and FRAME_CACHE_BYTES:
            return FRAME_CACHE_BYTES
        frame = current_frame()
        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=92, optimize=False)
        FRAME_CACHE_BYTES = buf.getvalue()
        FRAME_CACHE_KEY = key
        return FRAME_CACHE_BYTES


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsAdOverlay/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("AD_OVERLAY_LOG_REQUESTS", "0") == "1":
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            kind, _placeholder, sponsors, refreshed, error = STATE.snapshot()
            body = json.dumps(
                {
                    "ok": True,
                    "kind": kind,
                    "sponsorCount": len(sponsors),
                    "lastGoodRefresh": refreshed,
                    "lastError": error,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/frame.jpg"):
            body = jpeg_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if not self.path.startswith("/overlay.mjpg"):
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        interval = 1.0 / FPS
        try:
            while True:
                body = jpeg_bytes()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
                self.wfile.write(body)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(interval)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    try:
        STATE.update(load_feed_payload())
    except Exception as exc:
        STATE.error(exc)
    threading.Thread(target=poll_feed, name="sponsor-feed-poller", daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

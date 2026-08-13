#!/usr/bin/env python3
"""Dynamic FGBears full-screen advertising interstitial.

Polls the public Lovable sponsor feed and serves a 1280x720 MJPEG creative that
FFmpeg displays as a timed, full-screen interstitial in the live broadcast.
The feed already applies paid-ad -> House Ad -> placeholder priority.
"""
from __future__ import annotations

import io
import hashlib
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
PUBLISHED_FRAME = Path(os.getenv("AD_FRAME_FILE", "/srv/fgbears-live/runtime/ad-frame.jpg"))


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


def wrap_all_text(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Wrap without truncating so font fitting can consider the whole field."""
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
    lines.append(current)
    return lines


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    bold: bool = True,
) -> tuple[ImageFont.ImageFont, list[str], int]:
    """Fit an entire title, subtitle, or message inside a bounded TV-safe box."""
    normalized = " ".join(text.split())
    for size in range(start_size, min_size - 1, -2):
        fitted_font = font(size, bold=bold)
        lines = wrap_all_text(draw, normalized, fitted_font, max_width)
        line_height = max(size + 5, int(size * 1.16))
        if len(lines) <= max_lines and len(lines) * line_height <= max_height:
            return fitted_font, lines, line_height

    fitted_font = font(min_size, bold=bold)
    lines = wrap_all_text(draw, normalized, fitted_font, max_width)
    line_height = max(min_size + 5, int(min_size * 1.16))
    allowed = max(1, min(max_lines, max_height // line_height))
    if len(lines) > allowed:
        lines = lines[:allowed]
        last = lines[-1].rstrip(" .") + "…"
        while draw.textbbox((0, 0), last, font=fitted_font)[2] > max_width and len(last) > 2:
            last = last[:-2].rstrip() + "…"
        lines[-1] = last
    return fitted_font, lines, line_height


def draw_fitted_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: int,
    y: int,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
    max_lines: int,
    fill: str,
    bold: bool = True,
) -> int:
    if not text.strip():
        return y
    fitted_font, lines, line_height = fit_text_block(
        draw, text, max_width, max_height, start_size, min_size, max_lines, bold
    )
    for line in lines:
        draw.text((x, y), line, font=fitted_font, fill=fill)
        y += line_height
    return y


class SponsorState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.kind = "placeholder"
        self.placeholder = "Your Ad Here"
        self.sponsors: list[dict[str, Any]] = []
        self.last_good_refresh = 0.0
        self.last_error: str | None = None
        self._image_cache: dict[str, Image.Image] = {}
        self.frame_revision = 0
        self._visual_signature = ""

    @staticmethod
    def _stable_asset_url(url: str) -> str:
        """Treat refreshed signed URLs for the same stored asset as identical."""
        parsed = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @classmethod
    def _signature(cls, kind: str, placeholder: str, sponsors: list[dict[str, Any]]) -> str:
        stable_sponsors: list[dict[str, Any]] = []
        for sponsor in sponsors:
            stable = dict(sponsor)
            for key in ("imageUrl", "logoUrl"):
                if stable.get(key):
                    stable[key] = cls._stable_asset_url(str(stable[key]))
            stable_sponsors.append(stable)
        return json.dumps(
            {"kind": kind, "placeholder": placeholder, "sponsors": stable_sponsors},
            sort_keys=True,
            separators=(",", ":"),
        )

    def update(self, payload: dict[str, Any]) -> None:
        sponsors = payload.get("sponsors")
        if not isinstance(sponsors, list):
            raise ValueError("feed payload is missing sponsors[]")
        kind = str(payload.get("kind") or ("placeholder" if not sponsors else "paid"))
        placeholder = str(payload.get("placeholder") or "Your Ad Here")
        valid_sponsors = [s for s in sponsors if isinstance(s, dict)]
        signature = self._signature(kind, placeholder, valid_sponsors)
        with self._lock:
            self.kind = kind
            self.placeholder = placeholder
            self.sponsors = valid_sponsors
            if signature != self._visual_signature:
                self._visual_signature = signature
                self.frame_revision += 1
            self.last_good_refresh = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self._lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[str, str, list[dict[str, Any]], float, str | None, int]:
        with self._lock:
            return self.kind, self.placeholder, list(self.sponsors), self.last_good_refresh, self.last_error, self.frame_revision

    def image_for(self, url: str) -> Image.Image | None:
        if not url:
            return None
        cache_key = self._stable_asset_url(url)
        with self._lock:
            cached = self._image_cache.get(cache_key)
            if cached is not None:
                return cached.copy()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FGBears-Live/1.0"})
            with urllib.request.urlopen(req, timeout=8) as response:
                data = response.read(4_000_000)
            image = Image.open(io.BytesIO(data)).convert("RGBA")
            with self._lock:
                self._image_cache[cache_key] = image.copy()
                if len(self._image_cache) > 20:
                    self._image_cache.pop(next(iter(self._image_cache)))
            return image
        except Exception:
            return None


STATE = SponsorState()
FRAME_CACHE_LOCK = threading.Lock()
FRAME_CACHE_KEY: tuple[int, int] | None = None
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
            publish_frame()
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
        # Promote palette transparency to a real alpha channel before flattening
        # so Pillow does not warn during every creative refresh.
        return Image.open(io.BytesIO(encoded)).convert("RGBA").convert("RGB").resize((size, size), Image.Resampling.NEAREST)
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


def format_event_date(value: Any) -> str:
    """Format a feed date for a dedicated, TV-safe overlay line."""
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:T|$)", cleaned)
    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", cleaned)
    if iso_match:
        year, month, day = iso_match.groups()
    elif slash_match:
        month, day, year = slash_match.groups()
    else:
        return " ".join(cleaned.upper().split())[:48]
    months = ["", "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
    month_number = int(month)
    day_number = int(day)
    if not 1 <= month_number <= 12 or not 1 <= day_number <= 31:
        return " ".join(cleaned.upper().split())[:48]
    return f"{months[month_number]} {day_number}, {year}"


def sponsor_text_parts(sponsor: dict[str, Any], kind: str) -> tuple[str, str, str]:
    business = str(sponsor.get("businessName") or "Advertisement").strip()
    supplied_title = str(sponsor.get("title") or business).strip()
    subtitle = str(sponsor.get("subtitle") or "").strip()
    headline, embedded_date = house_event_parts(supplied_title) if kind == "house" else (supplied_title, "")
    supplied_date = next(
        (sponsor.get(key) for key in ("eventStartsAt", "eventDate", "date", "startsAt") if sponsor.get(key)),
        "",
    )
    return headline, subtitle, format_event_date(supplied_date) or embedded_date


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

    message = str(sponsor.get("promoMessage") or "").strip()
    website = str(sponsor.get("website") or "").strip()
    image_url = str(sponsor.get("imageUrl") or "").strip()
    creative = STATE.image_for(image_url) if image_url else None
    kind = STATE.snapshot()[0]
    headline, subtitle, event_date = sponsor_text_parts(sponsor, kind)
    draw_brand_frame(draw)
    draw_epic_media_qr(image, draw)
    draw.text((505, 112), "ADVERTISEMENT", font=font(20, bold=True), fill=BEARS_ORANGE)

    if creative is not None:
        box = (505, 145, WIDTH - 48, 330)
        target_w = box[2] - box[0]
        target_h = box[3] - box[1]
        fitted = ImageOps.contain(creative, (target_w, target_h)).convert("RGBA")
        canvas = Image.new("RGBA", (target_w, target_h), WHITE)
        canvas.alpha_composite(fitted, ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2))
        image.paste(canvas.convert("RGB"), (box[0], box[1]))
        text_x = 505
        text_w = WIDTH - text_x - 60
        y = draw_fitted_block(draw, headline.upper(), text_x, 348, text_w, 58, 36, 22, 2, BEARS_BLUE)
        y += 3
        y = draw_fitted_block(draw, subtitle.upper(), text_x, y, text_w, 30, 25, 17, 1, BEARS_ORANGE)
        y += 3
        y = draw_fitted_block(draw, event_date, text_x, y, text_w, 30, 25, 17, 1, BEARS_ORANGE)
        y += 4
        draw_fitted_block(draw, message.upper(), text_x, y, text_w, 44, 23, 16, 2, "#0B162A")
        if website:
            parsed = urllib.parse.urlsplit(website)
            site = parsed.netloc + parsed.path
            site_font = fit_text(draw, site, text_w, 20, 15)
            draw.text((text_x, 548), site, font=site_font, fill=BEARS_BLUE)
        add_epic_logo(image)
        return image

    # Text-only ads become complete broadcast creatives rather than sparse cards.
    text_x = 505
    text_w = WIDTH - text_x - 60
    y = draw_fitted_block(draw, headline.upper(), text_x, 165, text_w, 142, 64, 34, 3, BEARS_BLUE)
    y += 8
    y = draw_fitted_block(draw, subtitle.upper(), text_x, y, text_w, 52, 36, 22, 2, BEARS_ORANGE)
    y += 6
    y = draw_fitted_block(draw, event_date, text_x, y, text_w, 40, 32, 20, 1, BEARS_ORANGE)
    y += 10
    draw_fitted_block(draw, message.upper(), text_x, y, text_w, 110, 34, 18, 4, "#0B162A")

    if website:
        displayed_url = website
        site = urllib.parse.urlsplit(displayed_url).netloc + urllib.parse.urlsplit(displayed_url).path if displayed_url else ""
        site_font = fit_text(draw, site, text_w, 24, 17)
        draw.text((text_x, 548), site, font=site_font, fill=BEARS_BLUE)
    add_epic_logo(image)
    return image


def current_frame() -> Image.Image:
    _kind, placeholder, sponsors, _refreshed, _error, _revision = STATE.snapshot()
    if not sponsors:
        return render_placeholder(placeholder)
    index = int(time.time() // ROTATION_SECONDS) % len(sponsors)
    return render_sponsor(sponsors[index])


def jpeg_bytes() -> bytes:
    global FRAME_CACHE_BYTES, FRAME_CACHE_KEY
    _kind, _placeholder, sponsors, _refreshed, _error, revision = STATE.snapshot()
    rotation = int(time.time() // ROTATION_SECONDS) if len(sponsors) > 1 else 0
    key = (revision, rotation)
    with FRAME_CACHE_LOCK:
        if FRAME_CACHE_KEY == key and FRAME_CACHE_BYTES:
            return FRAME_CACHE_BYTES
        frame = current_frame()
        buf = io.BytesIO()
        frame.save(buf, format="JPEG", quality=92, optimize=False)
        FRAME_CACHE_BYTES = buf.getvalue()
        FRAME_CACHE_KEY = key
        return FRAME_CACHE_BYTES


def publish_frame() -> None:
    """Atomically publish the current creative for FFmpeg's local frame clock."""
    body = jpeg_bytes()
    digest = hashlib.sha256(body).hexdigest()
    digest_file = PUBLISHED_FRAME.with_suffix(".sha256")
    try:
        if PUBLISHED_FRAME.is_file() and digest_file.read_text(encoding="ascii").strip() == digest:
            return
    except OSError:
        pass
    PUBLISHED_FRAME.parent.mkdir(parents=True, exist_ok=True)
    temporary = PUBLISHED_FRAME.with_suffix(".partial.jpg")
    temporary.write_bytes(body)
    os.replace(temporary, PUBLISHED_FRAME)
    digest_file.write_text(digest + "\n", encoding="ascii")


class Handler(BaseHTTPRequestHandler):
    server_version = "FGBearsAdOverlay/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.getenv("AD_OVERLAY_LOG_REQUESTS", "0") == "1":
            super().log_message(fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/healthz"):
            kind, _placeholder, sponsors, refreshed, error, _revision = STATE.snapshot()
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
        next_frame_at = time.monotonic()
        try:
            while True:
                body = jpeg_bytes()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
                self.wfile.write(body)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                next_frame_at += interval
                delay = next_frame_at - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -interval:
                    # Do not let a slow client or one expensive refresh create
                    # permanent timing drift for the rest of the broadcast.
                    next_frame_at = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    try:
        STATE.update(load_feed_payload())
    except Exception as exc:
        STATE.error(exc)
    publish_frame()
    threading.Thread(target=poll_feed, name="sponsor-feed-poller", daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()

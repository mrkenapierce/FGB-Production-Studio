#!/usr/bin/env python3
"""Optional FGB trivia presentation layer for the existing ad renderer.

This module never owns the FFmpeg/YouTube transport. It decorates the current
ad renderer so a sanitized public game feed can temporarily replace only the
central advertising panel. If the game feed is absent, stale, malformed, or
inactive, the original ad renderer continues unchanged.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

GAME_FEED_URL = os.getenv(
    "GAME_SCREEN_FEED_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/game-screen",
)
GAME_FEED_FILE = os.getenv("GAME_SCREEN_FEED_FILE", "").strip()
GAME_POLL_SECONDS = max(1, int(os.getenv("GAME_SCREEN_POLL_SECONDS", "2")))
GAME_PLAY_BASE_URL = os.getenv("GAME_PLAY_BASE_URL", "https://epiccontentcreatorgrants.org").rstrip("/")
CREATIVE_FEED_URL = os.getenv(
    "CREATIVE_FEED_URL",
    "https://epiccontentcreatorgrants.org/api/public/fgbears/creatives",
)
CREATIVE_FEED_FILE = os.getenv("CREATIVE_FEED_FILE", "").strip()
CREATIVE_POLL_SECONDS = max(2, int(os.getenv("CREATIVE_POLL_SECONDS", "5")))
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))

BASE: Any = None
ORIGINAL_CURRENT_FRAME: Any = None
ORIGINAL_MAIN: Any = None


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _integer(value: Any, default: int, low: int, high: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _game_setting(game: dict[str, Any], key: str, default: Any = None) -> Any:
    """Accept both the flat broadcast contract and the current nested ads block."""
    if key in game and game.get(key) is not None:
        return game.get(key)
    ads = game.get("ads")
    if isinstance(ads, dict) and key in ads and ads.get(key) is not None:
        return ads.get(key)
    return default


class DurationState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.by_creative: dict[str, int] = {}
        self.last_error: str | None = None

    def update(self, payload: dict[str, Any]) -> None:
        mapping: dict[str, int] = {}
        entries: list[Any] = []
        primary = payload.get("primary")
        if isinstance(primary, list):
            entries.extend(primary)
        for key in ("fallback", "interstitial"):
            entry = payload.get(key)
            if isinstance(entry, dict):
                entries.append(entry)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            creative_id = str(entry.get("creativeId") or "").strip()
            if creative_id:
                mapping[creative_id] = _integer(entry.get("durationSeconds"), 20, 1, 300)
        with self.lock:
            self.by_creative = mapping
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def seconds(self, creative_id: str) -> int | None:
        with self.lock:
            return self.by_creative.get(creative_id)


DURATIONS = DurationState()


def _load_json_url(url: str, file_override: str = "") -> dict[str, Any]:
    if file_override:
        return json.loads(Path(file_override).read_text(encoding="utf-8"))
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(int(time.time()))))
    fresh = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )
    req = urllib.request.Request(
        fresh,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "FGBears-Live/2.0",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError(f"feed returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("feed must return an object")
        return payload


def load_creative_payload() -> dict[str, Any]:
    return _load_json_url(CREATIVE_FEED_URL, CREATIVE_FEED_FILE)


def poll_creative_feed() -> None:
    while True:
        try:
            DURATIONS.update(load_creative_payload())
        except Exception as exc:
            # Timing lookup is additive. Legacy sponsor timing remains a safe fallback.
            DURATIONS.error(exc)
        time.sleep(CREATIVE_POLL_SECONDS)


def ad_duration_seconds(sponsor: dict[str, Any]) -> int:
    """Use V2 resolved timing first, then the legacy sponsor timing as fallback."""
    creative_id = str(sponsor.get("creativeId") or "").strip()
    if creative_id:
        resolved = DURATIONS.seconds(creative_id)
        if resolved is not None:
            return _integer(resolved, 20, 1, 300)
    if sponsor.get("durationSeconds") is not None:
        return _integer(sponsor.get("durationSeconds"), 20, 3, 300)
    if sponsor.get("durationMs") is not None:
        try:
            return _integer(float(sponsor.get("durationMs")) / 1000.0, 20, 3, 300)
        except (TypeError, ValueError):
            pass
    return _integer(getattr(BASE, "ROTATION_SECONDS", 20), 20, 3, 300)


class GameState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.payload: dict[str, Any] = {"visible": False}
        self.last_error: str | None = None
        self.last_good_refresh = 0.0
        self.revision = 0
        self.signature = ""
        self.presentation_epoch = time.time()
        self.presentation_identity = ""

    def update(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ValueError("game-screen feed must return an object")
        sanitized = dict(payload)
        signature = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
        identity = json.dumps(
            {
                "gameId": sanitized.get("gameId") or sanitized.get("updatedAt") or sanitized.get("title"),
                "visible": _truthy(sanitized.get("visible")),
                "presentationMode": _game_setting(sanitized, "presentationMode", "crawl_only"),
                "adsEnabled": _game_setting(sanitized, "adsEnabled", False),
                "gameScreenSeconds": _game_setting(sanitized, "gameScreenSeconds", 20),
                "adsPerBreak": _game_setting(sanitized, "adsPerBreak", 1),
                "allowPaidAds": _game_setting(sanitized, "allowPaidAds", True),
                "allowHouseAds": _game_setting(sanitized, "allowHouseAds", True),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.lock:
            self.payload = sanitized
            if signature != self.signature:
                self.signature = signature
                self.revision += 1
            if identity != self.presentation_identity:
                self.presentation_identity = identity
                self.presentation_epoch = time.time()
            self.last_good_refresh = time.time()
            self.last_error = None

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.last_error = str(exc)

    def snapshot(self) -> tuple[dict[str, Any], float, str | None, int, float]:
        with self.lock:
            return (
                dict(self.payload),
                self.last_good_refresh,
                self.last_error,
                self.revision,
                self.presentation_epoch,
            )


GAME = GameState()
CACHE_LOCK = threading.Lock()
CACHE_KEY: tuple[Any, ...] | None = None
CACHE_BYTES = b""
RUNTIME_LOCK = threading.Lock()
RUNTIME_VALUE: tuple[str, bool] | None = None


def load_game_payload() -> dict[str, Any]:
    return _load_json_url(GAME_FEED_URL, GAME_FEED_FILE)


def poll_game_feed() -> None:
    while True:
        try:
            GAME.update(load_game_payload())
        except Exception as exc:
            # A trivia outage must never take advertising or the stream down.
            GAME.error(exc)
        time.sleep(GAME_POLL_SECONDS)


def _write_runtime(phase: str, keep_trivia_crawl: bool) -> None:
    global RUNTIME_VALUE
    value = (phase, keep_trivia_crawl)
    with RUNTIME_LOCK:
        if RUNTIME_VALUE == value:
            return
        RUNTIME_VALUE = value
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in (
            ("game-presentation-phase", phase),
            ("game-keep-trivia-crawl", "1" if keep_trivia_crawl else "0"),
        ):
            path = RUNTIME_DIR / name
            temporary = path.with_suffix(".partial")
            temporary.write_text(text + "\n", encoding="utf-8")
            os.replace(temporary, path)


def variable_rotation_slot(
    now: float,
    sponsors: list[dict[str, Any]],
    interstitial_available: bool | None = None,
    epoch: float | None = None,
) -> tuple[int, bool]:
    """Existing ad rotation, but with each sponsor's configured duration."""
    if not sponsors:
        return 0, False
    if interstitial_available is None:
        interstitial_available = BASE.HOUSE_INTERSTITIAL_PATH.is_file()
    start = BASE.ROTATION_EPOCH if epoch is None else epoch
    elapsed = max(0.0, now - start)
    segments: list[tuple[int, bool, int]] = []
    for index, sponsor in enumerate(sponsors):
        segments.append((index, False, ad_duration_seconds(sponsor)))
        if interstitial_available:
            segments.append((index, True, int(BASE.HOUSE_INTERSTITIAL_SECONDS)))
    total = sum(segment[2] for segment in segments)
    if total <= 0:
        return 0, False
    position = elapsed % total
    cursor = 0.0
    for index, house, seconds in segments:
        if position < cursor + seconds:
            return index, house
        cursor += seconds
    return segments[-1][0], segments[-1][1]


def _presentation_segments(
    game: dict[str, Any], kind: str, sponsors: list[dict[str, Any]]
) -> list[tuple[str, int, int | None]]:
    game_seconds = _integer(_game_setting(game, "gameScreenSeconds", 20), 20, 3, 300)
    ads_per_break = _integer(_game_setting(game, "adsPerBreak", 1), 1, 1, 5)
    allow_paid = _truthy(_game_setting(game, "allowPaidAds", True), True)
    allow_house = _truthy(_game_setting(game, "allowHouseAds", True), True)
    ads_enabled = _truthy(_game_setting(game, "adsEnabled", False), False)
    mode = str(_game_setting(game, "presentationMode", "crawl_only") or "crawl_only")
    if not ads_enabled or mode != "alternate_game_ads":
        return [("game", game_seconds, None)]

    eligible = sponsors
    if kind == "paid" and not allow_paid:
        eligible = []
    if kind == "house" and not allow_house:
        eligible = []

    segments: list[tuple[str, int, int | None]] = []
    if eligible:
        for start in range(0, len(eligible), ads_per_break):
            segments.append(("game", game_seconds, None))
            for index in range(start, min(start + ads_per_break, len(eligible))):
                segments.append(("ad", ad_duration_seconds(eligible[index]), index))
                # Preserve the existing paid-ad + EPIC house interstitial behavior.
                if kind == "paid" and allow_house and BASE.HOUSE_INTERSTITIAL_PATH.is_file():
                    segments.append(("house", int(BASE.HOUSE_INTERSTITIAL_SECONDS), None))
        return segments

    if allow_house and BASE.HOUSE_INTERSTITIAL_PATH.is_file():
        return [("game", game_seconds, None), ("house", int(BASE.HOUSE_INTERSTITIAL_SECONDS), None)]
    return [("game", game_seconds, None)]


def presentation_slot(
    now: float,
    game: dict[str, Any],
    kind: str,
    sponsors: list[dict[str, Any]],
    epoch: float,
) -> tuple[str, int | None, int]:
    segments = _presentation_segments(game, kind, sponsors)
    total = sum(max(1, segment[1]) for segment in segments)
    if total <= 0:
        return "game", None, 0
    position = max(0.0, now - epoch) % total
    cursor = 0.0
    for segment_index, (phase, seconds, sponsor_index) in enumerate(segments):
        if position < cursor + seconds:
            return phase, sponsor_index, segment_index
        cursor += seconds
    phase, _seconds, sponsor_index = segments[-1]
    return phase, sponsor_index, len(segments) - 1


def _iso_countdown(value: Any, now: float) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int(parsed.timestamp() - now + 0.999))
    except ValueError:
        return None


def _money(game: dict[str, Any]) -> str:
    displayed = str(game.get("currentPrize") or "").strip()
    if displayed:
        return displayed
    cents = game.get("currentPrizeCents")
    try:
        return f"${int(cents) / 100:,.2f}".replace(".00", "")
    except (TypeError, ValueError):
        return ""


def render_game_screen(game: dict[str, Any], now: float | None = None) -> Image.Image:
    now = time.time() if now is None else now
    image = Image.new("RGB", (BASE.WIDTH, BASE.HEIGHT), BASE.BEARS_BLUE)
    draw = ImageDraw.Draw(image)
    BASE.draw_brand_frame(draw)
    BASE.draw_epic_media_qr(image, draw)

    x1, y1, x2, y2 = BASE.AD_PANEL_BOX
    draw.rectangle(BASE.AD_PANEL_BACKGROUND_BOX, fill=BASE.BEARS_BLUE)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=16, fill="#07101F", outline=BASE.BEARS_ORANGE, width=4)

    title = str(game.get("title") or "ZIP SHOWDOWN").strip().upper()[:40]
    matchup = str(game.get("matchup") or "").strip().upper()[:80]
    prize = _money(game)
    phase = str(game.get("phase") or "question").lower()
    participants = _integer(game.get("participants"), 0, 0, 1_000_000)
    question_number = _integer(game.get("questionNumber"), 0, 0, 999)
    question_count = _integer(game.get("questionCount"), 0, 0, 999)
    countdown = _iso_countdown(game.get("phaseEndsAt"), now)

    draw.text((x1 + 24, y1 + 18), title, font=BASE.font(28, bold=True), fill=BASE.BEARS_ORANGE)
    if matchup:
        draw.text((x1 + 24, y1 + 55), matchup, font=BASE.font(20, bold=True), fill=BASE.WHITE)
    if prize:
        prize_label = f"CURRENT PRIZE: {prize}"
        prize_font = BASE.fit_text(draw, prize_label, 280, 24, 17)
        draw.text((x2 - 300, y1 + 20), prize_label, font=prize_font, fill=BASE.GOLD)
    if countdown is not None:
        clock = f"{countdown}s"
        clock_font = BASE.font(24, bold=True)
        width = draw.textbbox((0, 0), clock, font=clock_font)[2]
        draw.text((x2 - width - 26, y1 + 58), clock, font=clock_font, fill=BASE.WHITE)

    standings = game.get("standings") if isinstance(game.get("standings"), list) else []
    if phase == "scoreboard" or not game.get("prompt"):
        draw.text((x1 + 24, y1 + 105), "ZIP STANDINGS", font=BASE.font(31, bold=True), fill=BASE.WHITE)
        y = y1 + 155
        for rank, row in enumerate(standings[:5], 1):
            if not isinstance(row, dict):
                continue
            zip_code = str(row.get("zip") or "").strip()[:10]
            score = _integer(row.get("score"), 0, 0, 1_000_000)
            players = _integer(row.get("players") or row.get("participants"), 0, 0, 1_000_000)
            line = f"{rank}. {zip_code}   {score} PTS"
            if players:
                line += f"   •   {players} PLAYERS"
            draw.text((x1 + 34, y), line, font=BASE.font(26, bold=True), fill=BASE.WHITE)
            y += 50
    else:
        qlabel = "QUESTION"
        if question_number and question_count:
            qlabel = f"QUESTION {question_number} OF {question_count}"
        draw.text((x1 + 24, y1 + 105), qlabel, font=BASE.font(22, bold=True), fill=BASE.GOLD)
        prompt = str(game.get("prompt") or "").strip()
        y = BASE.draw_fitted_block(draw, prompt, x1 + 24, y1 + 140, 735, 92, 31, 21, 3, BASE.WHITE)
        choices = game.get("choices") if isinstance(game.get("choices"), list) else []
        y += 6
        for choice in choices[:4]:
            if not isinstance(choice, dict):
                continue
            key = str(choice.get("key") or "").strip().upper()[:1]
            text = str(choice.get("text") or "").strip()
            line = f"{key}) {text}" if key else text
            color = BASE.BEARS_ORANGE if phase == "revealed" and key and key == str(game.get("answer") or "").upper() else BASE.WHITE
            y = BASE.draw_fitted_block(draw, line, x1 + 36, y, 600, 45, 24, 17, 2, color)
            y += 3
        if phase == "revealed" and game.get("answer"):
            answer = str(game.get("answer")).upper()
            draw.text((x1 + 24, y2 - 50), f"ANSWER: {answer}", font=BASE.font(24, bold=True), fill=BASE.BEARS_ORANGE)

    if participants:
        draw.text((x1 + 24, y2 - 24), f"{participants} PLAYING", font=BASE.font(16, bold=True), fill=BASE.MUTED)

    play_path = str(game.get("playPath") or "/fgb/play").strip() or "/fgb/play"
    play_url = play_path if play_path.startswith("http") else f"{GAME_PLAY_BASE_URL}/{play_path.lstrip('/')}"
    qr = BASE.qr_for(play_url, 104)
    if qr is not None:
        qr_x, qr_y = x2 - 124, y2 - 126
        draw.rectangle((qr_x - 5, qr_y - 5, qr_x + 109, qr_y + 109), fill=BASE.WHITE)
        image.paste(qr, (qr_x, qr_y))
        draw.text((qr_x - 8, qr_y - 27), "SCAN TO PLAY", font=BASE.font(15, bold=True), fill=BASE.BEARS_ORANGE)

    BASE.add_epic_logo(image)
    return image


def current_frame(now: float | None = None) -> Image.Image:
    current_time = time.time() if now is None else now
    game, _game_refresh, _game_error, _game_revision, epoch = GAME.snapshot()
    visible = _truthy(game.get("visible"), False)
    kind, _placeholder, sponsors, _refresh, _error, _sponsor_revision = BASE.STATE.snapshot()

    if not visible:
        _write_runtime("inactive", True)
        return ORIGINAL_CURRENT_FRAME(current_time)

    mode = str(_game_setting(game, "presentationMode", "crawl_only") or "crawl_only")
    if mode != "alternate_game_ads":
        # Crawl-only trivia deliberately leaves the current ad panel untouched.
        _write_runtime("ad", True)
        return ORIGINAL_CURRENT_FRAME(current_time)

    phase, sponsor_index, _segment_index = presentation_slot(current_time, game, kind, sponsors, epoch)
    keep_crawl = _truthy(_game_setting(game, "keepTriviaCrawlDuringAds", True), True)
    _write_runtime(phase, keep_crawl)
    if phase == "game":
        return render_game_screen(game, current_time)
    if phase == "house":
        interstitial = BASE.render_house_interstitial()
        return interstitial if interstitial is not None else render_game_screen(game, current_time)
    if phase == "ad" and sponsor_index is not None and 0 <= sponsor_index < len(sponsors):
        return BASE.render_sponsor(sponsors[sponsor_index])
    return render_game_screen(game, current_time)


def jpeg_bytes() -> bytes:
    global CACHE_BYTES, CACHE_KEY
    kind, _placeholder, sponsors, _refresh, _error, sponsor_revision = BASE.STATE.snapshot()
    game, _game_refresh, _game_error, game_revision, epoch = GAME.snapshot()
    now = time.time()
    visible = _truthy(game.get("visible"), False)
    mode = str(_game_setting(game, "presentationMode", "crawl_only") or "crawl_only")
    if visible and mode == "alternate_game_ads":
        phase, sponsor_index, segment_index = presentation_slot(now, game, kind, sponsors, epoch)
        countdown = _iso_countdown(game.get("phaseEndsAt"), now) if phase == "game" else None
        key = (sponsor_revision, game_revision, phase, sponsor_index, segment_index, countdown)
    else:
        if sponsors:
            index, show_house = variable_rotation_slot(now, sponsors)
            key = (sponsor_revision, game_revision if visible else -1, "ad", index, int(show_house))
        else:
            key = (sponsor_revision, game_revision if visible else -1, "placeholder", -1, 0)
    with CACHE_LOCK:
        if CACHE_KEY == key and CACHE_BYTES:
            return CACHE_BYTES
        frame = current_frame(now)
        output = io.BytesIO()
        frame.save(output, format="JPEG", quality=92, optimize=False)
        CACHE_BYTES = output.getvalue()
        CACHE_KEY = key
        return CACHE_BYTES


def game_main() -> None:
    try:
        GAME.update(load_game_payload())
    except Exception as exc:
        GAME.error(exc)
    try:
        DURATIONS.update(load_creative_payload())
    except Exception as exc:
        DURATIONS.error(exc)
    threading.Thread(target=poll_game_feed, name="fgb-game-feed-poller", daemon=True).start()
    threading.Thread(target=poll_creative_feed, name="fgb-creative-feed-poller", daemon=True).start()
    ORIGINAL_MAIN()


def install(base: Any) -> None:
    """Attach the optional trivia presentation to the already-tested renderer."""
    global BASE, ORIGINAL_CURRENT_FRAME, ORIGINAL_MAIN
    BASE = base
    ORIGINAL_CURRENT_FRAME = base.current_frame
    ORIGINAL_MAIN = base.main
    base.rotation_slot = variable_rotation_slot
    base.current_frame = current_frame
    base.jpeg_bytes = jpeg_bytes
    base.main = game_main

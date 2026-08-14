#!/usr/bin/env python3
"""Poll the FGB-owned Bears RSS feed and publish one continuous news ribbon."""
from __future__ import annotations

import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED_URL = os.getenv(
    "BEARS_NEWS_FEED_URL",
    "https://raw.githubusercontent.com/mrkenapierce/FGB-Production-Studio/main/feeds/fgb-bears-news.xml",
)
FEED_FILE = os.getenv("BEARS_NEWS_FEED_FILE")
POLL_SECONDS = max(30, int(os.getenv("BEARS_NEWS_POLL_SECONDS", "300")))
MAX_ITEMS = max(1, min(20, int(os.getenv("BEARS_NEWS_MAX_ITEMS", "8"))))
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))
SEPARATOR = "     ◆     "


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.replace(temporary, path)


def normalize(value: str | None) -> str:
    return " ".join((value or "").replace("\n", " ").split())


def source_name(item: ET.Element) -> str:
    source = item.find("source")
    if source is not None and normalize(source.text):
        return normalize(source.text)
    link = normalize(item.findtext("link"))
    host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
    return host or "FGB SOURCE"


def read_feed_bytes() -> bytes:
    if FEED_FILE:
        return Path(FEED_FILE).read_bytes()
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Cache-Control": "no-cache",
            "User-Agent": "FGBears-Live-News/3.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def load_message() -> str:
    root = ET.fromstring(read_feed_bytes())
    messages: list[str] = []
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        title = normalize(item.findtext("title"))
        if not title:
            continue
        category = normalize(item.findtext("category")).lower()
        prefix = "BREAKING: " if category == "breaking" else ""
        source = source_name(item)
        # Preserve the complete headline and source. FFmpeg handles clipping and
        # scrolling; the feed never truncates editorial text.
        messages.append(f"{prefix}{title}  •  SOURCE: {source}")
    return SEPARATOR.join(messages)


def publish(message: str) -> None:
    active = bool(message)
    atomic_text(RUNTIME_DIR / "bears-news-label.txt", "BEARS NEWS" if active else "")
    atomic_text(RUNTIME_DIR / "bears-news-message.txt", message.upper() if active else "")
    atomic_text(RUNTIME_DIR / "bears-news-active", "1" if active else "0")


def main() -> None:
    last_good = ""
    while True:
        try:
            refreshed = load_message()
            if refreshed:
                last_good = refreshed
                publish(last_good)
            elif not last_good:
                publish("")
        except Exception as exc:
            print(f"Bears news feed refresh failed: {exc}", flush=True)
            if not last_good:
                publish("")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

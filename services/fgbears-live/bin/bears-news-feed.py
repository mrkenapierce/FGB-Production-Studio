#!/usr/bin/env python3
"""Poll the FGB-owned Bears RSS feed and publish one concise headline at a time."""
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
ROTATE_SECONDS = max(8, int(os.getenv("BEARS_NEWS_ROTATE_SECONDS", "30")))
MAX_ITEMS = max(1, min(20, int(os.getenv("BEARS_NEWS_MAX_ITEMS", "8"))))
RUNTIME_DIR = Path(os.getenv("CRAWL_RUNTIME_DIR", "/srv/fgbears-live/runtime"))


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


def shorten(value: str, limit: int) -> str:
    value = normalize(value)
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip(" -–—,:;") + "…"


def read_feed_bytes() -> bytes:
    if FEED_FILE:
        return Path(FEED_FILE).read_bytes()
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "Cache-Control": "no-cache",
            "User-Agent": "FGBears-Live-News/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read()


def load_items() -> list[dict[str, str]]:
    root = ET.fromstring(read_feed_bytes())
    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:MAX_ITEMS]:
        # Preserve normal news headlines instead of forcing them into the old
        # lower-third width. The upper-third renderer decides whether to hold
        # them static or scroll them when they exceed the available viewport.
        title = shorten(item.findtext("title") or "", 140)
        if not title:
            continue
        category = normalize(item.findtext("category")).lower()
        label = "BREAKING BEARS" if category == "breaking" else "BEARS NEWS"
        source = shorten(source_name(item), 24)
        items.append({"label": label, "message": f"{title}  •  SOURCE: {source}"})
    return items


def publish(item: dict[str, str] | None) -> None:
    if item is None:
        atomic_text(RUNTIME_DIR / "bears-news-label.txt", "")
        atomic_text(RUNTIME_DIR / "bears-news-message.txt", "")
        atomic_text(RUNTIME_DIR / "bears-news-active", "0")
        return
    atomic_text(RUNTIME_DIR / "bears-news-label.txt", item["label"].upper())
    atomic_text(RUNTIME_DIR / "bears-news-message.txt", item["message"].upper())
    atomic_text(RUNTIME_DIR / "bears-news-active", "1")


def main() -> None:
    items: list[dict[str, str]] = []
    index = 0
    next_poll = 0.0
    while True:
        now = time.monotonic()
        if now >= next_poll:
            try:
                refreshed = load_items()
                if refreshed:
                    items = refreshed
                    index %= len(items)
                elif not items:
                    publish(None)
            except Exception as exc:
                print(f"Bears news feed refresh failed: {exc}", flush=True)
                if not items:
                    publish(None)
            next_poll = now + POLL_SECONDS

        if items:
            publish(items[index])
            index = (index + 1) % len(items)
        time.sleep(ROTATE_SECONDS)


if __name__ == "__main__":
    main()

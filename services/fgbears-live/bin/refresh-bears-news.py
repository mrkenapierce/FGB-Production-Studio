#!/usr/bin/env python3
"""Generate the FGB Bears RSS feed locally on the Oracle broadcast host.

The GitHub-hosted feed remains the public/canonical repository copy. This local
copy exists so the live ribbon is not dependent on GitHub Actions schedule
latency. The script is safe to invoke every five minutes; it scans at most once
per configured interval bucket and preserves the last good feed on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable

FEED_PATH = Path(os.getenv("FGB_BEARS_NEWS_FEED_PATH", "/srv/fgbears-live/runtime/fgb-bears-news.xml"))
STATUS_PATH = Path(os.getenv("FGB_BEARS_NEWS_STATUS_PATH", "/srv/fgbears-live/runtime/bears-news-refresh-status.env"))
MAX_ITEMS = 8
MIN_ITEMS = 3
MAX_AGE = timedelta(days=7)
USER_AGENT = "FootballsGreatestBearsNews/2.0 (+https://www.youtube.com/@FootballsGreatestBears)"

SOURCE_RULES = (
    ("ChicagoBears.com", "chicagobears.com", "https://www.chicagobears.com/"),
    ("ESPN", "espn.com", "https://www.espn.com/nfl/team/_/name/chi/chicago-bears"),
    ("NFL.com", "nfl.com", "https://www.nfl.com/teams/chicago-bears/"),
    ("NBC Sports Chicago", "nbcsportschicago.com", "https://www.nbcsportschicago.com/"),
    ("CBS Sports", "cbssports.com", "https://www.cbssports.com/nfl/teams/CHI/chicago-bears/"),
    ("Yahoo Sports", "sports.yahoo.com", "https://sports.yahoo.com/nfl/teams/chicago/"),
    ("Pro Football Talk", "nbcsports.com/nfl/profootballtalk", "https://www.nbcsports.com/nfl/profootballtalk"),
    ("The Athletic", "nytimes.com/athletic", "https://www.nytimes.com/athletic/nfl/team/bears/"),
    ("Sports Illustrated", "si.com/nfl/bears", "https://www.si.com/nfl/bears/"),
)

RSS_ENDPOINTS = (
    "https://www.chicagobears.com/rss/news",
    "https://www.nfl.com/feeds-rs/news/all-news.xml",
    "https://www.nbcsports.com/nfl/profootballtalk.rss",
    "https://www.nbcsportschicago.com/feed/",
    "https://www.cbssports.com/rss/headlines/nfl/",
    "https://sports.yahoo.com/nfl/rss.xml",
    "https://www.si.com/rss/si_nfl.rss",
)


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    source_name: str
    source_url: str
    published_at: datetime


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def read_status() -> dict[str, str]:
    if not STATUS_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in STATUS_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def write_status(*, status: str, now: int, slot: int, item_count: int, changed: bool, error: str = "") -> None:
    safe_error = re.sub(r"[^A-Za-z0-9_.:/ -]+", " ", error).strip()[:240]
    atomic_write(
        STATUS_PATH,
        "\n".join(
            (
                f"STATUS={status}",
                f"LAST_SCAN_EPOCH={now}",
                f"LAST_SLOT={slot}",
                f"ITEM_COUNT={item_count}",
                f"FEED_CHANGED={1 if changed else 0}",
                f"ERROR={safe_error}",
            )
        )
        + "\n",
    )


def fetch_bytes(url: str, *, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, application/json;q=0.9, */*;q=0.1",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def normalize_text(value: str | None) -> str:
    return " ".join(html.unescape(value or "").replace("\n", " ").split())


def clean_title(value: str) -> str:
    title = normalize_text(re.sub(r"<[^>]+>", " ", value))
    return re.sub(
        r"\s+-\s+(Chicago Bears|ESPN|NFL\.com|CBS Sports|Yahoo Sports|Sports Illustrated|The Athletic|NBC Sports.*)$",
        "",
        title,
        flags=re.I,
    ).strip()


def parse_date(value: str | None) -> datetime | None:
    raw = normalize_text(value)
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def strip_tracking(raw_url: str) -> str:
    url = normalize_text(raw_url)
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"}:
        return ""
    query = []
    for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if re.match(r"^(utm_|ocid$|cmpid$|guccounter$|output$)", key, flags=re.I):
            continue
        query.append((key, value))
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def classify_source(raw_url: str) -> tuple[str, str] | None:
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except ValueError:
        return None
    host = parsed.hostname.lower().removeprefix("www.") if parsed.hostname else ""
    path = parsed.path.lower()
    if host == "chicagobears.com" or host.endswith(".chicagobears.com"):
        return "ChicagoBears.com", "https://www.chicagobears.com/"
    if host == "espn.com" or host.endswith(".espn.com"):
        return "ESPN", "https://www.espn.com/nfl/team/_/name/chi/chicago-bears"
    if host == "nfl.com" or host.endswith(".nfl.com"):
        return "NFL.com", "https://www.nfl.com/teams/chicago-bears/"
    if host == "nbcsportschicago.com" or host.endswith(".nbcsportschicago.com") or ((host == "nbcsports.com" or host.endswith(".nbcsports.com")) and path.startswith("/chicago/")):
        return "NBC Sports Chicago", "https://www.nbcsportschicago.com/"
    if host == "cbssports.com" or host.endswith(".cbssports.com"):
        return "CBS Sports", "https://www.cbssports.com/nfl/teams/CHI/chicago-bears/"
    if host == "yahoo.com" or host.endswith(".yahoo.com"):
        return "Yahoo Sports", "https://sports.yahoo.com/nfl/teams/chicago/"
    if (host == "nbcsports.com" or host.endswith(".nbcsports.com")) and path.startswith("/nfl/profootballtalk"):
        return "Pro Football Talk", "https://www.nbcsports.com/nfl/profootballtalk"
    if (host == "nytimes.com" or host.endswith(".nytimes.com")) and path.startswith("/athletic/"):
        return "The Athletic", "https://www.nytimes.com/athletic/nfl/team/bears/"
    if host == "si.com" or host.endswith(".si.com"):
        return "Sports Illustrated", "https://www.si.com/nfl/bears/"
    return None


def item_link(item: ET.Element) -> str:
    text_link = normalize_text(item.findtext("link"))
    if text_link:
        return text_link
    for link in item.findall("link"):
        href = normalize_text(link.attrib.get("href"))
        if href:
            return href
    return ""


def parse_xml_feed(data: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(data)
    items: list[dict[str, str]] = []
    candidates = list(root.findall(".//item")) + list(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
    for item in candidates:
        title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
        published = (
            item.findtext("pubDate")
            or item.findtext("{http://purl.org/dc/elements/1.1/}date")
            or item.findtext("{http://www.w3.org/2005/Atom}published")
            or item.findtext("{http://www.w3.org/2005/Atom}updated")
            or ""
        )
        link = item_link(item)
        if not link:
            atom_link = item.find("{http://www.w3.org/2005/Atom}link")
            link = normalize_text(atom_link.attrib.get("href")) if atom_link is not None else ""
        items.append({"title": clean_title(title), "url": strip_tracking(link), "published": published})
    return items


def fetch_espn() -> list[dict[str, str]]:
    data = json.loads(fetch_bytes("https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/chi/news").decode("utf-8"))
    output = []
    for article in data.get("articles", []):
        links = article.get("links") or {}
        web = links.get("web") or {}
        api_news = (links.get("api") or {}).get("news") or {}
        output.append(
            {
                "title": clean_title(str(article.get("headline") or "")),
                "url": strip_tracking(str(web.get("href") or api_news.get("href") or "")),
                "published": str(article.get("published") or article.get("lastModified") or ""),
            }
        )
    return output


def fetch_bing(search_domain: str) -> list[dict[str, str]]:
    query = urllib.parse.quote(f'"Chicago Bears" site:{search_domain}')
    url = f"https://www.bing.com/news/search?q={query}&format=rss&setlang=en-US&count=30&qft=interval%3d%227%22"
    return parse_xml_feed(fetch_bytes(url))


def normalize_article(raw: dict[str, str], now: datetime) -> Article | None:
    title = clean_title(raw.get("title", ""))
    url = strip_tracking(raw.get("url", ""))
    source = classify_source(url)
    published = parse_date(raw.get("published"))
    if not title or not url or not source or not published:
        return None
    if not re.search(r"\b(chicago bears|bears|halas hall)\b", title, flags=re.I):
        return None
    if published > now + timedelta(hours=1) or now - published > MAX_AGE:
        return None
    return Article(title=title, url=url, source_name=source[0], source_url=source[1], published_at=published)


def gather_articles(now: datetime) -> tuple[list[Article], int]:
    raw_articles: list[dict[str, str]] = []
    failures = 0
    jobs: list[tuple[str, callable]] = [("ESPN", fetch_espn)]
    jobs.extend((url, lambda u=url: parse_xml_feed(fetch_bytes(u))) for url in RSS_ENDPOINTS)
    jobs.extend((name, lambda d=domain: fetch_bing(d)) for name, domain, _ in SOURCE_RULES)
    for _name, job in jobs:
        try:
            raw_articles.extend(job())
        except Exception:
            failures += 1

    unique: dict[str, Article] = {}
    for raw in raw_articles:
        article = normalize_article(raw, now)
        if not article:
            continue
        key = article.url.rstrip("/").lower()
        unique.setdefault(key, article)

    selected: list[Article] = []
    per_source: dict[str, int] = {}
    for article in sorted(unique.values(), key=lambda value: value.published_at, reverse=True):
        count = per_source.get(article.source_name, 0)
        if count >= 2:
            continue
        selected.append(article)
        per_source[article.source_name] = count + 1
        if len(selected) >= MAX_ITEMS:
            break
    return selected, failures


def existing_signature() -> str:
    if not FEED_PATH.exists():
        return ""
    try:
        root = ET.fromstring(FEED_PATH.read_bytes())
    except ET.ParseError:
        return ""
    values = []
    for item in root.findall("./channel/item"):
        values.append(f"{normalize_text(item.findtext('link'))}\n{normalize_text(item.findtext('title'))}")
    return "\n---\n".join(values)


def article_signature(items: Iterable[Article]) -> str:
    return "\n---\n".join(f"{item.url}\n{item.title}" for item in items)


def xml_escape(value: str) -> str:
    return html.escape(value, quote=True).replace("&#x27;", "&apos;")


def render_feed(items: list[Article], now: datetime) -> str:
    blocks = []
    for item in items:
        guid = hashlib.sha256(item.url.encode("utf-8")).hexdigest()[:20]
        description = f"Football's Greatest Bears news brief from {item.source_name}: {item.title}"
        blocks.append(
            "\n".join(
                (
                    "    <item>",
                    f"      <title>{xml_escape(item.title)}</title>",
                    f"      <description>{xml_escape(description)}</description>",
                    f"      <link>{xml_escape(item.url)}</link>",
                    f'      <guid isPermaLink="false">footballs-greatest-bears-news-{guid}</guid>',
                    f"      <pubDate>{item.published_at.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>",
                    "      <category>normal</category>",
                    f'      <source url="{xml_escape(item.source_url)}">{xml_escape(item.source_name)}</source>',
                    "    </item>",
                )
            )
        )
    rendered = "\n\n".join(blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Football&apos;s Greatest Bears News</title>\n"
        "    <link>https://www.youtube.com/@FootballsGreatestBears</link>\n"
        "    <description>Current Chicago Bears headlines from approved sources for Football&apos;s Greatest Bears live programming.</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S GMT')}</lastBuildDate>\n"
        "    <ttl>5</ttl>\n"
        '    <atom:link href="https://raw.githubusercontent.com/mrkenapierce/FGB-Production-Studio/main/feeds/fgb-bears-news.xml" rel="self" type="application/rss+xml" />\n\n'
        f"{rendered}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    interval = max(300, args.interval_seconds)
    now_epoch = int(time.time())
    slot = now_epoch // interval
    previous = read_status()
    if not args.force and previous.get("LAST_SLOT") == str(slot):
        return 0

    now = datetime.now(timezone.utc)
    try:
        articles, failures = gather_articles(now)
        if len(articles) < MIN_ITEMS:
            raise RuntimeError(f"only {len(articles)} approved fresh items found; {failures} source scans failed")
        changed = existing_signature() != article_signature(articles)
        if changed:
            atomic_write(FEED_PATH, render_feed(articles, now))
        write_status(status="OK", now=now_epoch, slot=slot, item_count=len(articles), changed=changed)
        print(f"Bears news scan OK: items={len(articles)} changed={int(changed)} failures={failures}", flush=True)
        return 0
    except Exception as exc:
        existing_count = 0
        try:
            existing_count = len(ET.fromstring(FEED_PATH.read_bytes()).findall("./channel/item")) if FEED_PATH.exists() else 0
        except Exception:
            existing_count = 0
        write_status(status="ERROR", now=now_epoch, slot=slot, item_count=existing_count, changed=False, error=str(exc))
        print(f"Bears news scan failed; existing local feed preserved: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

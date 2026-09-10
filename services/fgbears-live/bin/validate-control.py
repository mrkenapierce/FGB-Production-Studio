#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime

SUPPORTED_TYPES = {
    "ad",
    "trivia_question",
    "trivia_reveal",
    "giveaway",
    "house",
    "live_message",
    "fallback",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_iso(value: str, field: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(f"{field} must be ISO-8601: {value}")


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "services/fgbears-live/control/schedule.json"
    root = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else ".")

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if data.get("schema_version") != 1:
        fail("schema_version must equal 1")
    if not data.get("channel"):
        fail("channel is required")
    if not data.get("timezone"):
        fail("timezone is required")
    if not isinstance(data.get("revision"), int) or data["revision"] < 1:
        fail("revision must be a positive integer")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        fail("items must be a non-empty array")

    seen = set()
    active_fallbacks = 0
    for index, item in enumerate(items):
        prefix = f"items[{index}]"
        item_id = item.get("id")
        if not item_id or not isinstance(item_id, str):
            fail(f"{prefix}.id is required")
        if item_id in seen:
            fail(f"duplicate item id: {item_id}")
        seen.add(item_id)

        item_type = item.get("type")
        if item_type not in SUPPORTED_TYPES:
            fail(f"{prefix}.type unsupported: {item_type}")

        duration = item.get("duration_seconds")
        if not isinstance(duration, int) or duration < 1 or duration > 3600:
            fail(f"{prefix}.duration_seconds must be 1..3600")

        frequency = item.get("frequency_per_hour", 0)
        if not isinstance(frequency, int) or frequency < 0 or frequency > 60:
            fail(f"{prefix}.frequency_per_hour must be 0..60")

        priority = item.get("priority", 0)
        if not isinstance(priority, int):
            fail(f"{prefix}.priority must be an integer")

        asset = item.get("asset")
        if not asset or not isinstance(asset, str):
            fail(f"{prefix}.asset is required")
        asset_path = os.path.abspath(os.path.join(root, asset))
        if not asset_path.startswith(root + os.sep):
            fail(f"{prefix}.asset escapes repository root")
        if not os.path.isfile(asset_path):
            fail(f"{prefix}.asset does not exist: {asset}")

        if "start_at" in item:
            parse_iso(item["start_at"], f"{prefix}.start_at")
        if "end_at" in item:
            parse_iso(item["end_at"], f"{prefix}.end_at")
        if item.get("active") is True and item_type == "fallback":
            active_fallbacks += 1

    fallback_asset = data.get("fallback_asset")
    if not fallback_asset:
        fail("fallback_asset is required")
    fallback_path = os.path.abspath(os.path.join(root, fallback_asset))
    if not os.path.isfile(fallback_path):
        fail(f"fallback_asset does not exist: {fallback_asset}")
    if active_fallbacks < 1:
        fail("at least one active fallback item is required")

    print(f"Control schedule valid: {len(items)} item(s), revision {data['revision']}")


if __name__ == "__main__":
    main()

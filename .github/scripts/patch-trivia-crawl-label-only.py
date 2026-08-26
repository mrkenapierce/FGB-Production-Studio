#!/usr/bin/env python3
from pathlib import Path

path = Path('services/fgbears-live/bin/crawl-overlay.py')
text = path.read_text(encoding='utf-8')

old = '''        label = grapheme_slice(str(payload.get("label") or "EPIC LIVE"), 24)\n        message_parts: list[str] = []\n'''
new = '''        label = grapheme_slice(str(payload.get("label") or "EPIC LIVE"), 24)\n        trivia_mode = (\n            bool(payload.get("triviaActive"))\n            or str(payload.get("mode") or "").strip().casefold() == "trivia"\n            or str(payload.get("type") or "").strip().casefold() == "trivia"\n            or label.strip().casefold() == "trivia"\n        )\n        message_parts: list[str] = []\n'''
if old not in text:
    raise SystemExit('Could not locate label/message block')
text = text.replace(old, new, 1)

old = '''        message = grapheme_slice(message, 3200)\n        message_count = len(message_parts) if message_parts else (1 if message else 0)\n'''
new = '''        message = grapheme_slice(message, 3200)\n        if trivia_mode:\n            # Trivia questions belong only in the dedicated trivia/QR overlay.\n            # The lower crawl remains present as a label-only "Trivia" lane.\n            message = ""\n        message_count = 0 if trivia_mode else (len(message_parts) if message_parts else (1 if message else 0))\n'''
if old not in text:
    raise SystemExit('Could not locate message finalization block')
text = text.replace(old, new, 1)

old = '''        if value["active"] and message:\n            prime_emoji_cache(label, message)\n'''
new = '''        if value["active"] and (label or message):\n            prime_emoji_cache(label, message)\n'''
if old not in text:
    raise SystemExit('Could not locate emoji cache block')
text = text.replace(old, new, 1)

old = '''def publish_text(value: dict[str, Any]) -> None:\n    active = bool(value["active"] and value["message"])\n'''
new = '''def publish_text(value: dict[str, Any]) -> None:\n    active = bool(value["active"] and (value["label"] or value["message"]))\n'''
if old not in text:
    raise SystemExit('Could not locate publish_text active predicate')
text = text.replace(old, new, 1)

old = '''    if not value["active"] or not value["message"]:\n        return image\n\n    label = value["label"].upper()\n'''
new = '''    if not value["active"]:\n        return image\n\n    label = value["label"].upper()\n'''
if old not in text:
    raise SystemExit('Could not locate frame active predicate')
text = text.replace(old, new, 1)

old = '''    image.paste(label_line, (label_x, label_y), label_line)\n\n    message = value["message"].upper().strip()\n'''
new = '''    image.paste(label_line, (label_x, label_y), label_line)\n\n    if not value["message"]:\n        return image\n\n    message = value["message"].upper().strip()\n'''
if old not in text:
    raise SystemExit('Could not locate label/message rendering boundary')
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
print('Trivia crawl is now label-only; trivia questions remain in the dedicated overlay.')

#!/usr/bin/env python3
"""Composite the exact locked YouTube→Rumble card into the live trivia panel.

The source card is treated as one immutable 1280x720 image. Nothing inside the
card is redrawn, reflowed, cropped, or independently resized. The whole image is
uniformly scaled to fit the production AD_PANEL_BOX and centered there.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = (1280, 720)
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 462, 104, 798, 470
PANEL_COLOR = "#0B162A"
EXPECTED_SOURCE = (1280, 720)


def compose(frame_path: Path, source_card_path: Path, output_path: Path) -> dict[str, object]:
    with Image.open(frame_path) as raw_frame:
        frame = raw_frame.convert("RGB")
    if frame.size != CANVAS:
        raise ValueError(f"program frame must be {CANVAS}, got {frame.size}")

    with Image.open(source_card_path) as raw_source:
        source = raw_source.convert("RGB")
    if source.size != EXPECTED_SOURCE:
        raise ValueError(f"locked source card must be {EXPECTED_SOURCE}, got {source.size}")

    # Preserve the exact card's aspect ratio. Pillow's thumbnail calculation for
    # 1280x720 inside 798x470 yields 798x449; no crop/stretch/re-layout occurs.
    card = source.copy()
    card.thumbnail((PANEL_W, PANEL_H), Image.Resampling.LANCZOS)
    card_w, card_h = card.size
    card_x = PANEL_X + (PANEL_W - card_w) // 2
    card_y = PANEL_Y + (PANEL_H - card_h) // 2

    # Clear the complete production trivia panel so no pre-question/ad pixels can
    # show around the aspect-preserved card. The letterbox uses the card's locked
    # navy background and stays entirely between the news and crawl layers.
    draw = ImageDraw.Draw(frame)
    draw.rectangle(
        (PANEL_X, PANEL_Y, PANEL_X + PANEL_W - 1, PANEL_Y + PANEL_H - 1),
        fill=PANEL_COLOR,
    )
    frame.paste(card, (card_x, card_y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(output_path, format="PNG", optimize=False)
    return {
        "canvas": list(CANVAS),
        "panel": {"x": PANEL_X, "y": PANEL_Y, "width": PANEL_W, "height": PANEL_H},
        "sourceCard": {"width": source.width, "height": source.height},
        "scaledCard": {"x": card_x, "y": card_y, "width": card_w, "height": card_h},
        "mode": "exact-locked-template-whole-card",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frame", type=Path)
    parser.add_argument("source_card", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(compose(args.frame, args.source_card, args.output), sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the locked 1280×720 YouTube→Rumble trivia redirect creative."""
from __future__ import annotations

import argparse
import io
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH, HEIGHT = 1280, 720
BACKGROUND = "#0B162A"
TOP_BAR = "#C83803"
BOTTOM_BAR = "#07101F"
WHITE = "#FFFFFF"
MUTED = "#D5D9E2"
GOLD = "#F2B134"
RUMBLE_URL = "https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html"
RUMBLE_DISPLAY = "rumble.com/v7eqrsu"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size=size)


def qr_image(url: str, size: int) -> Image.Image:
    """Generate the QR with the already-required qrencode binary, not a Python package."""
    encoded = subprocess.run(
        ["qrencode", "-t", "PNG", "-o", "-", "-l", "M", "-s", "10", "-m", "0", url],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout
    mono = Image.open(io.BytesIO(encoded)).convert("L")
    branded = ImageOps.colorize(mono, black=BACKGROUND, white=WHITE).convert("RGB")
    return branded.resize((size, size), Image.Resampling.NEAREST)


def build() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 93), fill=TOP_BAR)
    draw.rectangle((0, 624, WIDTH, HEIGHT - 1), fill=BOTTOM_BAR)
    # Lovable locked-template geometry: 18px inset / 5px border.
    draw.rectangle((18, 18, WIDTH - 18, HEIGHT - 18), outline=TOP_BAR, width=5)

    draw.text((72, 30), "YOUTUBE VIEWERS", font=font(30, True), fill=WHITE)
    draw.text((72, 146), "TRIVIA IS LIVE", font=font(66, True), fill=WHITE)
    draw.text((72, 224), "ON RUMBLE", font=font(82, True), fill=TOP_BAR)
    draw.text((76, 334), "PLAY NOW FOR CASH PRIZES", font=font(31, True), fill=GOLD)
    draw.text((76, 386), "Scan the QR code to join the live game.", font=font(27), fill=WHITE)
    draw.text(
        (76, 428),
        "No purchase required. Eligibility and official rules apply.",
        font=font(20),
        fill=MUTED,
    )

    qr_card = (864, 122, 1204, 514)
    draw.rounded_rectangle(qr_card, radius=18, fill=WHITE, outline=TOP_BAR, width=5)

    qr_img = qr_image(RUMBLE_URL, 300)
    image.paste(qr_img, (884, 142))

    label = "SCAN TO PLAY"
    label_font = font(24, True)
    bbox = draw.textbbox((0, 0), label, font=label_font)
    label_x = 864 + (340 - (bbox[2] - bbox[0])) // 2
    draw.text((label_x, 468), label, font=label_font, fill=BACKGROUND)

    draw.text((72, 647), "OR VISIT", font=font(21, True), fill=MUTED)
    draw.text((230, 638), RUMBLE_DISPLAY, font=font(38, True), fill=WHITE)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="youtube-rumble-trivia.png")
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    build().save(path, format="PNG", optimize=True)
    print(path)


if __name__ == "__main__":
    main()

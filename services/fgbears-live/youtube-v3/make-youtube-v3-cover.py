#!/usr/bin/env python3
from pathlib import Path
import qrcode
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 798, 470
OUT = Path('/opt/fgbears-live/youtube-v3/youtube-trivia-cover.png')
RUMBLE_URL = 'https://rumble.com/v7eqrsu-chicago-bears-live-trivia-every-20-minutes-cash-prizes-fgb.html'
RUMBLE_DISPLAY = 'rumble.com/v7eqrsu'
REGULAR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else REGULAR, size=size)

def main():
    w, h = 1280, 720
    bg, orange, bottom = '#0B162A', '#C83803', '#07101F'
    white, muted, gold = '#FFFFFF', '#D5D9E2', '#F2B134'
    image = Image.new('RGB', (w, h), bg)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, w, 93), fill=orange)
    draw.rectangle((0, 624, w, h - 1), fill=bottom)
    draw.rectangle((18, 18, w - 18, h - 18), outline=orange, width=5)
    draw.text((72, 30), 'YOUTUBE VIEWERS', font=font(30, True), fill=white)
    draw.text((72, 146), 'TRIVIA IS LIVE', font=font(66, True), fill=white)
    draw.text((72, 224), 'ON RUMBLE', font=font(82, True), fill=orange)
    draw.text((76, 334), 'PLAY NOW FOR CASH PRIZES', font=font(31, True), fill=gold)
    draw.text((76, 386), 'Scan the QR code to join the live game.', font=font(27), fill=white)
    draw.text((76, 428), 'No purchase required. Eligibility and official rules apply.', font=font(20), fill=muted)
    draw.rounded_rectangle((864, 122, 1204, 514), radius=18, fill=white, outline=orange, width=5)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=0)
    qr.add_data(RUMBLE_URL); qr.make(fit=True)
    qr_img = qr.make_image(fill_color=bg, back_color=white).convert('RGB').resize((300, 300), Image.Resampling.NEAREST)
    image.paste(qr_img, (884, 142))
    label = 'SCAN TO PLAY'; lf = font(24, True); box = draw.textbbox((0,0), label, font=lf)
    draw.text((864 + (340 - (box[2]-box[0]))//2, 468), label, font=lf, fill=bg)
    draw.text((72, 647), 'OR VISIT', font=font(21, True), fill=muted)
    draw.text((230, 638), RUMBLE_DISPLAY, font=font(38, True), fill=white)
    source = image.convert('RGBA')
    source.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    out = Image.new('RGBA', (WIDTH, HEIGHT), (11, 22, 42, 255))
    out.paste(source, ((WIDTH-source.width)//2, (HEIGHT-source.height)//2), source)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, 'PNG')
    print(f'COVER=PASS path={OUT} size={out.width}x{out.height}')

if __name__ == '__main__':
    main()

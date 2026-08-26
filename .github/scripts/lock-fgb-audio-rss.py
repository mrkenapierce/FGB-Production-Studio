#!/usr/bin/env python3
from pathlib import Path
import re

START = Path('services/fgbears-live/bin/start-stream.sh')
INSTALL = Path('services/fgbears-live/bin/install.sh')
ENV = Path('services/fgbears-live/config/stream.env.example')

s = START.read_text()
s = re.sub(
    r': "\$\{PODCAST_AUDIO_FILTER:=[^"]*\}"',
    "CANONICAL_AUDIO_FILTER='volume=-2dB,aresample=48000:first_pts=0'",
    s,
    count=1,
)
s = s.replace('-af "$PODCAST_AUDIO_FILTER"', '-af "$CANONICAL_AUDIO_FILTER"')
s = s.replace(': "${BEARS_NEWS_SCROLL_PPS:=90}"', ': "${BEARS_NEWS_SCROLL_PPS:=76}"')
s = s.replace('crop=w=970:h=68:x=277:y=23', 'crop=w=990:h=68:x=267:y=23')
s = s.replace('drawbox=x=0:y=0:w=970:h=68:color=0x07101F@0.98:t=fill', 'drawbox=x=0:y=0:w=990:h=68:color=0x07101F@0.98:t=fill')
s = s.replace('fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS\\,text_w+970)', 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\\,text_w+990)')
s = s.replace('drawbox=x=257:y=23:w=5:h=68:color=0x0B162A:t=fill,drawbox=x=262:y=23:w=5:h=68:color=0xC83803:t=fill', 'drawbox=x=262:y=23:w=5:h=68:color=0xC83803:t=fill')
s = s.replace('fontcolor=white:fontsize=24:x=18+(239-text_w)/2:y=44', 'fontcolor=white:fontsize=29:x=18+(239-text_w)/2:y=39')
s = s.replace('[base][newslane]overlay=x=277:y=23:shortest=1', '[base][newslane]overlay=x=267:y=23:shortest=1')
old_tee = '''TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}"
OUTPUT_LABELS=("YouTube local UDP mirror")
TEE_TARGETS+="|[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${X_LOCAL_UDP_URL}"
OUTPUT_LABELS+=("X local mirror")
TEE_TARGETS+="|[f=mpegts:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${INSTAGRAM_LOCAL_UDP_URL}"
OUTPUT_LABELS+=("Instagram local mirror")
'''
new_tee = '''TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}"
OUTPUT_LABELS=("YouTube local UDP mirror")
'''
s = s.replace(old_tee, new_tee)
START.write_text(s)

i = INSTALL.read_text()
i = i.replace('"PODCAST_AUDIO_FILTER": "loudnorm=I=-14:LRA=11:TP=-1.5,aresample=48000:first_pts=0",', '"PODCAST_AUDIO_FILTER": "volume=-2dB,aresample=48000:first_pts=0",')
if '"BEARS_NEWS_SCROLL_PPS": "76",' not in i:
    i = i.replace('updates = {\n', 'updates = {\n    "BEARS_NEWS_SCROLL_PPS": "76",\n')
i = re.sub(
    r'x_relay_enabled = values\.get\("X_RELAY_ENABLED"\).*?instagram_relay_enabled = values\.get\("INSTAGRAM_RELAY_ENABLED", "0"\)\n',
    'x_relay_enabled = "0"\ninstagram_relay_enabled = "0"\n',
    i,
    flags=re.S,
)
i = i.replace('"X_RELAY_ENABLED": x_relay_enabled,', '"X_RELAY_ENABLED": "0",')
i = i.replace('"INSTAGRAM_RELAY_ENABLED": instagram_relay_enabled,', '"INSTAGRAM_RELAY_ENABLED": "0",')
INSTALL.write_text(i)

e = ENV.read_text()
lines = []
seen_news = False
for line in e.splitlines():
    if line.startswith('PODCAST_AUDIO_FILTER='):
        line = 'PODCAST_AUDIO_FILTER=volume=-2dB,aresample=48000:first_pts=0'
    elif line.startswith('BEARS_NEWS_SCROLL_PPS='):
        line = 'BEARS_NEWS_SCROLL_PPS=76'
        seen_news = True
    elif line.startswith('X_RELAY_ENABLED='):
        line = 'X_RELAY_ENABLED=0'
    elif line.startswith('INSTAGRAM_RELAY_ENABLED='):
        line = 'INSTAGRAM_RELAY_ENABLED=0'
    lines.append(line)
if not seen_news:
    lines.append('BEARS_NEWS_SCROLL_PPS=76')
ENV.write_text('\n'.join(lines) + '\n')

# Deterministic postconditions.
s = START.read_text()
i = INSTALL.read_text()
e = ENV.read_text()
assert ': "${BEARS_NEWS_SCROLL_PPS:=76}"' in s
assert 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS' in s
assert 'fontcolor=white:fontsize=29:x=18+(239-text_w)/2:y=39' in s
assert 'drawbox=x=257:y=23:w=5:h=68:color=0x0B162A' not in s
assert "CANONICAL_AUDIO_FILTER='volume=-2dB,aresample=48000:first_pts=0'" in s
assert '-af "$CANONICAL_AUDIO_FILTER"' in s
assert '-af "$PODCAST_AUDIO_FILTER"' not in s
assert 'loudnorm=' not in i
assert 'BEARS_NEWS_SCROLL_PPS=76' in e
assert 'X local mirror' not in s
assert 'Instagram local mirror' not in s
print('RSS/audio production correction applied.')

#!/usr/bin/env python3
from pathlib import Path

ROOT = Path('services/fgbears-live')
START = ROOT / 'bin/start-stream.sh'
CRAWL = ROOT / 'bin/crawl-overlay.py'
INVAR = ROOT / 'tests/test-production-invariants.sh'
NEWS_TEST = ROOT / 'tests/test-bears-news.sh'
SCRIPT_TEST = ROOT / 'tests/test-scripts.sh'
LOCK_HELPER = Path('.github/scripts/lock-fgb-audio-rss.py')

# RSS/news: eliminate the visible internal blue receiving gutters. The text
# viewport now runs directly from the orange divider to the right orange border.
s = START.read_text()
s = s.replace('crop=w=970:h=68:x=277:y=23', 'crop=w=990:h=68:x=267:y=23')
s = s.replace('drawbox=x=0:y=0:w=970:h=68:color=0x07101F@0.98:t=fill', 'drawbox=x=0:y=0:w=990:h=68:color=0x07101F@0.98:t=fill')
s = s.replace('fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS\\,text_w+970)', 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\\,text_w+990)')
s = s.replace('[base][newslane]overlay=x=277:y=23:shortest=1', '[base][newslane]overlay=x=267:y=23:shortest=1')
START.write_text(s)

# Main Crawl: same behavior. No 12px dark-blue entry/exit gutter; glyphs are
# clipped at the actual orange divider/right border instead.
c = CRAWL.read_text()
c = c.replace('viewport_start = 279', 'viewport_start = 267')
c = c.replace('viewport_width = 966', 'viewport_width = 990')
c = c.replace(
    '# Keep moving glyphs clear of the divider and right border so partial letters\n'
    '    # do not appear glued to, or sliced directly against, the frame.\n',
    '# Clip moving glyphs at the actual orange divider/right border so there is\n'
    '    # no visible dark-blue receiving gutter at either end of the crawl.\n',
)
CRAWL.write_text(c)

# Permanent helper: never narrow RSS back to the obsolete 970px/277px geometry.
h = LOCK_HELPER.read_text()
h = h.replace("s = s.replace('crop=w=990:h=68:x=267:y=23', 'crop=w=970:h=68:x=277:y=23')", "s = s.replace('crop=w=970:h=68:x=277:y=23', 'crop=w=990:h=68:x=267:y=23')")
h = h.replace("s = s.replace('drawbox=x=0:y=0:w=990:h=68:color=0x07101F@0.98:t=fill', 'drawbox=x=0:y=0:w=970:h=68:color=0x07101F@0.98:t=fill')", "s = s.replace('drawbox=x=0:y=0:w=970:h=68:color=0x07101F@0.98:t=fill', 'drawbox=x=0:y=0:w=990:h=68:color=0x07101F@0.98:t=fill')")
h = h.replace("s = s.replace('fontsize=25:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\\\\,text_w+990)', 'fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS\\\\,text_w+970)')", "s = s.replace('fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS\\\\,text_w+970)', 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\\\\,text_w+990)')")
h = h.replace("s = s.replace('[base][newslane]overlay=x=267:y=23:shortest=1', '[base][newslane]overlay=x=277:y=23:shortest=1')", "s = s.replace('[base][newslane]overlay=x=277:y=23:shortest=1', '[base][newslane]overlay=x=267:y=23:shortest=1')")
h = h.replace("assert 'fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS' in s", "assert 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS' in s")
LOCK_HELPER.write_text(h)

# Production invariant follows the Main Crawl exemplar and rejects the obsolete
# internal blue gutters.
i = INVAR.read_text()
i = i.replace("grep -Fq 'fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS' \"$START\"", "grep -Fq 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS' \"$START\"")
i = i.replace(" || fail 'RSS/news message typography/motion geometry diverged from Main Crawl.'\"", " || fail 'RSS/news message typography/motion geometry diverged from Main Crawl.'") if False else i
# The first replacement above is easier/safer to normalize explicitly if shell quoting was unchanged.
i = i.replace("grep -Fq 'fontsize=31:x=970-mod(t*$BEARS_NEWS_SCROLL_PPS' \"$START\" || fail", "grep -Fq 'fontsize=31:x=990-mod(t*$BEARS_NEWS_SCROLL_PPS' \"$START\" || fail")
if "crop=w=970:h=68:x=277:y=23" not in i:
    marker = "# RULE 2 — Audio is immutable at runtime.\n"
    guard = "if grep -Fq 'crop=w=970:h=68:x=277:y=23' \"$START\"; then\n  fail 'RSS/news crawl reintroduced the obsolete internal blue clipping gutter.'\nfi\n\n"
    i = i.replace(marker, guard + marker)
INVAR.write_text(i)

# News regression test: canonical speed + full 990px lane + the complete long
# headline must survive into the runtime message without editorial truncation.
t = NEWS_TEST.read_text()
t = t.replace("grep -q '^BEARS_NEWS_SCROLL_PPS=90$'", "grep -q '^BEARS_NEWS_SCROLL_PPS=76$'")
t = t.replace("graph = graph.replace('$BEARS_NEWS_SCROLL_PPS', '90')", "graph = graph.replace('$BEARS_NEWS_SCROLL_PPS', '76')")
needle = "grep -q 'CHICAGOBEARS.COM' \"$TMP/runtime/bears-news-message.txt\"\n"
full = "grep -Fq 'THIS IS A DELIBERATELY LONG CHICAGO BEARS HEADLINE THAT MUST REMAIN COMPLETE THROUGH THE SOURCE' \"$TMP/runtime/bears-news-message.txt\"\n"
if full not in t:
    t = t.replace(needle, full + needle)
NEWS_TEST.write_text(t)

# Older integration test must validate the immutable canonical audio variable,
# not the retired environment-overridable filter.
st = SCRIPT_TEST.read_text()
st = st.replace("grep -Fq 'PODCAST_AUDIO_FILTER:=volume=-2dB,aresample=48000:first_pts=0' \"$ROOT/bin/start-stream.sh\"", "grep -Fq \"CANONICAL_AUDIO_FILTER='volume=-2dB,aresample=48000:first_pts=0'\" \"$ROOT/bin/start-stream.sh\"")
SCRIPT_TEST.write_text(st)

# Hard postconditions.
s = START.read_text(); c = CRAWL.read_text(); h = LOCK_HELPER.read_text()
assert 'crop=w=990:h=68:x=267:y=23' in s
assert 'x=990-mod(t*$BEARS_NEWS_SCROLL_PPS\\,text_w+990)' in s
assert '[base][newslane]overlay=x=267:y=23:shortest=1' in s
assert 'crop=w=970:h=68:x=277:y=23' not in s
assert 'viewport_start = 267' in c
assert 'viewport_width = 990' in c
assert "crop=w=970:h=68:x=277:y=23', 'crop=w=990:h=68:x=267:y=23" in h
print('FGB ribbon clipping and RSS completeness repair applied.')

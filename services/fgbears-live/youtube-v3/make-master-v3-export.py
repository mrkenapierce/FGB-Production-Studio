#!/usr/bin/env python3
"""Produce the v3.6 master launcher from the canonical shared-master launcher."""
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
s = src.read_text(encoding='utf-8')
needle = ': "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"\n'
assert needle in s
s = s.replace(needle, needle + ': "${YOUTUBE_V3_LOCAL_UDP_URL:=udp://127.0.0.1:1950?pkt_size=1316}"\n', 1)
needle = '[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78\n'
assert needle in s
s = s.replace(needle, needle + '[[ "$YOUTUBE_V3_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78\n', 1)
s = s.replace('writes the same finished program directly to two\n# loopback MPEG-TS sockets.', 'writes the same finished program directly to three\n# loopback MPEG-TS sockets.', 1)
old = 'TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}|[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${RUMBLE_LOCAL_UDP_URL}"'
assert old in s
new = old[:-1] + '|[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_V3_LOCAL_UDP_URL}"'
s = s.replace(old, new, 1)
assert s.count('YOUTUBE_V3_LOCAL_UDP_URL') == 3
assert ':1950?pkt_size=1316' in s
dst.write_text(s, encoding='utf-8')
print(f'MASTER_V3_EXPORT=PASS output={dst}')

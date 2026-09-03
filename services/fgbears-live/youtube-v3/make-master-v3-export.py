#!/usr/bin/env python3
"""Add the v3.6 UDP export to a canonical FGB shared-master launcher.

This intentionally preserves every existing behavior (including FIFO recovery,
overlay startup, thread settings, and cleanup logic) and changes only three
contract points: the v3 URL variable, its loopback validation, and the tee
subscriber list. The transformation is idempotent and supports both the live
/usr/local launcher and the repository launcher syntax.
"""
from pathlib import Path
import sys

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
s = src.read_text(encoding="utf-8")
original = s

rumble_var = ': "${RUMBLE_LOCAL_UDP_URL:=udp://127.0.0.1:1940?pkt_size=1316}"'
v3_var = ': "${YOUTUBE_V3_LOCAL_UDP_URL:=udp://127.0.0.1:1950?pkt_size=1316}"'
assert rumble_var in s, "Rumble UDP variable not found"
if v3_var not in s:
    s = s.replace(rumble_var + "\n", rumble_var + "\n" + v3_var + "\n", 1)

v3_single = '[[ "$YOUTUBE_V3_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78'
v3_block = '''[[ "$YOUTUBE_V3_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "YOUTUBE_V3_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}'''
if v3_single not in s and v3_block not in s:
    rumble_single = '[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || exit 78'
    if rumble_single in s:
        s = s.replace(rumble_single + "\n", rumble_single + "\n" + v3_single + "\n", 1)
    else:
        rumble_block = '''[[ "$RUMBLE_LOCAL_UDP_URL" == udp://127.0.0.1:* ]] || {
  echo "RUMBLE_LOCAL_UDP_URL must remain a loopback UDP URL." >&2
  exit 78
}'''
        assert rumble_block in s, "Rumble UDP validation not found"
        s = s.replace(rumble_block, rumble_block + "\n" + v3_block, 1)

lines = s.splitlines()
tee_index = next((i for i, line in enumerate(lines) if line.startswith('TEE_TARGETS="')), None)
assert tee_index is not None, "TEE_TARGETS not found"
if '${YOUTUBE_V3_LOCAL_UDP_URL}' not in lines[tee_index]:
    assert lines[tee_index].endswith('"'), "Unexpected TEE_TARGETS syntax"
    lines[tee_index] = lines[tee_index][:-1] + '|[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_V3_LOCAL_UDP_URL}"'
s = "\n".join(lines) + ("\n" if original.endswith("\n") else "")

# Preservation gates: v3 must be added exactly once at each contract point,
# while the live master's important resilience controls remain unchanged.
assert s.count("YOUTUBE_V3_LOCAL_UDP_URL") == 3, s.count("YOUTUBE_V3_LOCAL_UDP_URL")
assert ':1950?pkt_size=1316' in s
for token in ('-use_fifo 1', 'TEE_FIFO_OPTIONS'):
    if token in original:
        assert s.count(token) == original.count(token), f"preservation failure: {token}"
for token in ('AD_OVERLAY_SCRIPT', 'CRAWL_OVERLAY_SCRIPT', 'BEARS_NEWS_SCRIPT', 'VIDEO_GOP'):
    assert s.count(token) == original.count(token), f"preservation failure: {token}"

# No platform credentials are introduced into the master transformation.
assert 'rtmps://a.rtmps.youtube.com' not in s

dst.write_text(s, encoding="utf-8")
print(f"MASTER_V3_EXPORT=PASS input={src} output={dst} preserved_fifo={'-use_fifo 1' in original}")

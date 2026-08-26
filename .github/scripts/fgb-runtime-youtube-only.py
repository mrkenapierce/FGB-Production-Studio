#!/usr/bin/env python3
from pathlib import Path
import re

REPLACEMENT = (
    'TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}"\n'
    "printf 'FGBears Live output: YouTube local UDP mirror only.\\n'\n\n"
)

for raw in ('/usr/local/bin/fgbears-start-stream', '/opt/fgbears-live/bin/start-stream.sh'):
    path = Path(raw)
    if not path.exists():
        continue
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'^: "\$\{(?:X|INSTAGRAM|FACEBOOK)_[A-Z0-9_]+.*\n', '', text, flags=re.M)
    start = text.find('case "${X_STREAM_ENABLED,,}" in')
    end = text.find('python3 "$AD_OVERLAY_SCRIPT"', start if start >= 0 else 0)
    if start >= 0 and end > start:
        text = text[:start] + REPLACEMENT + text[end:]
    else:
        tee = text.find('TEE_TARGETS=')
        end = text.find('python3 "$AD_OVERLAY_SCRIPT"', tee if tee >= 0 else 0)
        if tee >= 0 and end > tee:
            text = text[:tee] + REPLACEMENT + text[end:]
    forbidden = ('1937', '1938', 'X local mirror', 'Instagram local mirror', 'Facebook local mirror')
    if any(item in text for item in forbidden):
        raise SystemExit(f'Failed to remove social tee outputs from {raw}')
    path.write_text(text, encoding='utf-8')
    path.chmod(0o755)

env = Path('/etc/fgbears-live/stream.env')
if env.exists():
    lines = env.read_text(encoding='utf-8').splitlines()
    lines = [line for line in lines if not line.startswith(('X_', 'INSTAGRAM_', 'FACEBOOK_'))]
    env.write_text('\n'.join(lines) + '\n', encoding='utf-8')

print('Oracle FGB runtime locked to YouTube only')

#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
LIVE = ROOT / "services" / "fgbears-live"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


# 1. Primary encoder: YouTube is the sole tee output.
path = LIVE / "bin" / "start-stream.sh"
text = read(path)
text = re.sub(r'^: "\$\{(?:X|INSTAGRAM)_[A-Z0-9_]+.*\n', '', text, flags=re.M)
start = text.find('case "${X_STREAM_ENABLED,,}" in')
end = text.find('python3 "$AD_OVERLAY_SCRIPT"', start)
require(start >= 0 and end > start, "Could not locate social tee block in start-stream.sh")
text = text[:start] + '''TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}"
printf 'FGBears Live output: YouTube local UDP mirror only.\n'

''' + text[end:]
require('1937' not in text and '1938' not in text, "Retired social UDP ports remain in start-stream.sh")
require('X_' not in text and 'INSTAGRAM_' not in text, "Retired social environment keys remain in start-stream.sh")
write(path, text)


# 2. Installer: install only core + isolated YouTube relay. Also remove social
# keys from existing stream.env during migration, so old hosts cannot resurrect them.
path = LIVE / "bin" / "install.sh"
text = read(path)
for line in (
    'install -m 0755 /opt/fgbears-live/bin/x-relay.sh /usr/local/bin/fgbears-x-relay\n',
    'install -m 0755 /opt/fgbears-live/bin/instagram-relay.sh /usr/local/bin/fgbears-instagram-relay\n',
    'install -m 0755 /opt/fgbears-live/bin/configure-x.sh /usr/local/bin/fgbears-configure-x\n',
    'install -m 0755 /opt/fgbears-live/bin/configure-instagram.sh /usr/local/bin/fgbears-configure-instagram\n',
):
    text = text.replace(line, '')
text = re.sub(
    r'for platform in x instagram; do\n  for unit in relay\.service start\.service stop\.service start\.timer stop\.timer; do\n    install -m 0644 .*?\n  done\ndone\n',
    '', text, flags=re.S,
)
text = text.replace(
    "# Preserve credentials, migrate YouTube's internal handoff to connectionless\n# loopback MPEG-TS and keep the remaining social schedules independent of\n# the primary encoder.",
    "# Preserve credentials and migrate YouTube's internal handoff to the isolated\n# loopback MPEG-TS relay. Remove all retired social-simulcast keys.",
)
block_start = text.find('python3 - "$ENV_PATH" <<\'PY\'')
block_end = text.find('\nPY\nchown root:fgbears "$ENV_PATH"', block_start)
require(block_start >= 0 and block_end > block_start, "Could not locate stream.env migration block")
new_env_block = '''python3 - "$ENV_PATH" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key] = value

current_base = values.get("YOUTUBE_RTMP_BASE", "")
upstream = values.get("YOUTUBE_UPSTREAM_RTMP_BASE", "")
if not upstream:
    if current_base and not current_base.startswith("rtmp://127.0.0.1:"):
        upstream = current_base
    else:
        upstream = "rtmps://a.rtmps.youtube.com/live2"

updates = {
    "PODCAST_AUDIO_FILTER": "volume=-2dB,aresample=48000:first_pts=0",
    "YOUTUBE_LOCAL_UDP_URL": "udp://127.0.0.1:1939?pkt_size=1316",
    "YOUTUBE_UPSTREAM_RTMP_BASE": upstream,
}
retired_prefixes = ("X_", "INSTAGRAM_", "FACEBOOK_")
seen = set()
out = []
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key = line.split("=", 1)[0]
        if key.startswith(retired_prefixes):
            continue
        if key in updates:
            if key not in seen:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
            continue
    out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\\n".join(out) + "\\n", encoding="utf-8")
PY'''
text = text[:block_start] + new_env_block + text[block_end + len('\nPY'):]
# Remove all scheduling/configuration logic between YouTube enable and relay comment.
social_start = text.find('systemctl disable fgbears-x-relay.service')
youtube_comment = text.find('# The YouTube relay remains', social_start)
require(social_start >= 0 and youtube_comment > social_start, "Could not locate social runtime configuration block")
text = text[:social_start] + text[youtube_comment:]
text = text.replace(
    'Installed FGBears Live with one primary encode, isolated YouTube UDP relay, and X/Instagram sidecars scheduled 09:00-17:00 America/Chicago.',
    'Installed FGBears Live in YouTube-only mode with one primary encode and an isolated YouTube UDP relay.',
)
require('1937' not in text and '1938' not in text, "Retired social UDP ports remain in install.sh")
require('fgbears-x-' not in text and 'fgbears-instagram-' not in text, "Retired social units remain in install.sh")
write(path, text)


# 3. Health monitor: no social reconciliation, timers or sidecar incidents.
path = LIVE / "bin" / "healthcheck.sh"
text = read(path)
start = text.find('reconcile_social_relay() {')
end = text.find('# News scanning is independent', start)
require(start >= 0 and end > start, "Could not locate social health block")
text = text[:start] + text[end:]
text = re.sub(r'^reconcile_social_relay .*\n', '', text, flags=re.M)
require('reconcile_social_relay' not in text, "Social health reconciliation remains")
write(path, text)


# 4. Status sampler: remove social schedule, service/socket checks and output fields.
path = LIVE / "bin" / "stream-status.sh"
text = read(path)
text = re.sub(r'^ENV_FILE=.*\n', '', text, flags=re.M)
start = text.find('central_hm=')
end = text.find('news_refresh_status=', start)
require(start >= 0 and end > start, "Could not locate social status block")
text = text[:start] + text[end:]
text = re.sub(r"^printf 'SOCIAL_WINDOW_ACTIVE=.*\n", '', text, flags=re.M)
text = re.sub(r"^printf 'X_ENABLED=.*\n", '', text, flags=re.M)
text = re.sub(r"^printf 'INSTAGRAM_ENABLED=.*\n", '', text, flags=re.M)
require('social_state' not in text and 'X_RELAY' not in text and 'INSTAGRAM_' not in text, "Social status checks remain")
write(path, text)


# 5. Environment example: only YouTube transport credentials remain.
path = LIVE / "config" / "stream.env.example"
lines = [line for line in read(path).splitlines() if not line.startswith(('X_', 'INSTAGRAM_', 'FACEBOOK_'))]
text = '\n'.join(lines) + '\n'
text = text.replace('Never commit an actual YouTube, X, or Instagram stream key.', 'Never commit an actual YouTube stream key.')
write(path, text)


# 6. Transport test becomes a hard YouTube-only invariant.
path = LIVE / "tests" / "test-multistream.sh"
write(path, r'''#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for script in "$ROOT/bin/start-stream.sh" "$ROOT/bin/youtube-relay.sh" "$ROOT/bin/install.sh" "$ROOT/bin/healthcheck.sh" "$ROOT/bin/stream-status.sh"; do
  bash -n "$script"
done

for retired in \
  "$ROOT/bin/x-relay.sh" "$ROOT/bin/instagram-relay.sh" \
  "$ROOT/bin/configure-x.sh" "$ROOT/bin/configure-instagram.sh" \
  "$ROOT/systemd/fgbears-x-relay.service" "$ROOT/systemd/fgbears-x-start.service" "$ROOT/systemd/fgbears-x-stop.service" "$ROOT/systemd/fgbears-x-start.timer" "$ROOT/systemd/fgbears-x-stop.timer" \
  "$ROOT/systemd/fgbears-instagram-relay.service" "$ROOT/systemd/fgbears-instagram-start.service" "$ROOT/systemd/fgbears-instagram-stop.service" "$ROOT/systemd/fgbears-instagram-start.timer" "$ROOT/systemd/fgbears-instagram-stop.timer" \
  "$ROOT/bin/facebook-relay.sh" "$ROOT/bin/configure-facebook.sh"; do
  test ! -e "$retired"
done

if grep -R -nE 'X_LOCAL_UDP_URL|X_RELAY_ENABLED|X_STREAM_ENABLED|INSTAGRAM_LOCAL_UDP_URL|INSTAGRAM_RELAY_ENABLED|FACEBOOK_LOCAL_UDP_URL|fgbears-(x|instagram|facebook)-relay|X local mirror|Instagram local mirror|Facebook local mirror' "$ROOT/bin" "$ROOT/config" "$ROOT/systemd"; then
  echo 'Retired social simulcast protocol remains in active FGB livestream code.' >&2
  exit 1
fi

grep -Fq 'TEE_TARGETS="[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]${YOUTUBE_LOCAL_UDP_URL}"' "$ROOT/bin/start-stream.sh"
grep -Fq 'YouTube local UDP mirror only' "$ROOT/bin/start-stream.sh"

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -hide_banner -loglevel error \
    -f lavfi -i testsrc2=size=320x180:rate=24 \
    -f lavfi -i sine=frequency=440:sample_rate=48000 \
    -t 0.5 -map 0:v -map 1:a \
    -c:v libx264 -preset ultrafast -g 48 -c:a aac -b:a 128k \
    -f tee -use_fifo 1 -fifo_options 'attempt_recovery=1:recover_any_error=1:recovery_wait_time=1' \
    "[f=mpegts:mpegts_flags=resend_headers:bsfs/v=dump_extra=freq=keyframe:onfail=ignore]$TMP/youtube-local.ts"
  test -s "$TMP/youtube-local.ts"
  ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=aac$'
  ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1 "$TMP/youtube-local.ts" | grep -q '^codec_name=h264$'
fi

echo 'FGBears transport is locked to YouTube only.'
''')


# 7. Deployment status no longer advertises social capability.
path = ROOT / ".github" / "workflows" / "fgbears-live-deploy.yml"
if path.exists():
    text = read(path)
    text = text.replace(',xSimulcastCapable:true,xAccountHandle:"@epic501c3"', '')
    write(path, text)


# 8. Remove source files and workflows that can recreate the sidecars.
for rel in (
    "bin/x-relay.sh",
    "bin/instagram-relay.sh",
    "bin/configure-x.sh",
    "bin/configure-instagram.sh",
    "systemd/fgbears-x-relay.service",
    "systemd/fgbears-x-start.service",
    "systemd/fgbears-x-stop.service",
    "systemd/fgbears-x-start.timer",
    "systemd/fgbears-x-stop.timer",
    "systemd/fgbears-instagram-relay.service",
    "systemd/fgbears-instagram-start.service",
    "systemd/fgbears-instagram-stop.service",
    "systemd/fgbears-instagram-start.timer",
    "systemd/fgbears-instagram-stop.timer",
):
    target = LIVE / rel
    if target.exists():
        target.unlink()

workflow_dir = ROOT / ".github" / "workflows"
for workflow in workflow_dir.glob("*.yml"):
    if workflow.name in {"fgbears-live-deploy.yml", "fgbears-live-validate.yml", "fgbears-live-monitor.yml"}:
        continue
    body = read(workflow)
    if re.search(r'X_RELAY_ENABLED|INSTAGRAM_RELAY_ENABLED|fgbears-x-relay|fgbears-instagram-relay|configure-x\.sh|configure-instagram\.sh', body):
        workflow.unlink()

# The old one-shot audio patch is obsolete and repeatedly tries to mutate live
# defaults on every edit to itself. Remove it while this source cleanup is active.
obsolete_audio_patch = workflow_dir / "patch-live-audio-headroom.yml"
if obsolete_audio_patch.exists():
    obsolete_audio_patch.unlink()

print("YouTube-only source migration complete")

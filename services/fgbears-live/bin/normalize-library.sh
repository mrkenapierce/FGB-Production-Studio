#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: normalize-library.sh INPUT [OUTPUT]

Standardizes one owned/authorized episode for the 24/7 FGB relay and applies
OFFLINE two-pass loudness normalization. The live encoder does not perform
loudness normalization.

Audio profile: fgb-podcast-v1
  ingest target: -14 LUFS integrated, -1.5 dBTP, LRA 11
  live safety stage: -2 dB + 48 kHz resample
  expected YouTube-bound program loudness: approximately -16 LUFS
USAGE
}

[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 64; }
INPUT=$1
[[ -f "$INPUT" ]] || { echo "Input does not exist: $INPUT" >&2; exit 66; }

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
OUTPUT=${2:-"$MEDIA_DIR/$(basename "${INPUT%.*}").mp4"}
[[ "$INPUT" != "$OUTPUT" ]] || { echo "Input and output must be different paths." >&2; exit 64; }
mkdir -p "$(dirname "$OUTPUT")"

PROFILE_VERSION=${FGB_AUDIO_PROFILE_VERSION:-fgb-podcast-v1}
LOUDNESS_TARGET_I=${FGB_LOUDNESS_TARGET_I:--14}
LOUDNESS_TARGET_LRA=${FGB_LOUDNESS_TARGET_LRA:-11}
LOUDNESS_TARGET_TP=${FGB_LOUDNESS_TARGET_TP:--1.5}
LOUDNESS_TOLERANCE_LU=${FGB_LOUDNESS_TOLERANCE_LU:-0.8}
MAX_POST_TRUE_PEAK=${FGB_MAX_POST_TRUE_PEAK:--1.0}

TMP_OUTPUT="${OUTPUT%.mp4}.partial.mp4"
MEASURE_LOG=$(mktemp)
VERIFY_LOG=$(mktemp)
trap 'rm -f "$TMP_OUTPUT" "$MEASURE_LOG" "$VERIFY_LOG"' EXIT

if ! ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$INPUT" | grep -q .; then
  echo "Input has no audio stream; refusing to place silent media into the FGB playlist: $INPUT" >&2
  exit 65
fi

# First pass: measure the complete program. This runs offline, never in the live
# encoder, so it cannot warp timestamps or impose real-time DSP load.
ffmpeg -hide_banner -nostdin -v info -i "$INPUT" -map 0:a:0 -vn \
  -af "loudnorm=I=${LOUDNESS_TARGET_I}:LRA=${LOUDNESS_TARGET_LRA}:TP=${LOUDNESS_TARGET_TP}:print_format=json" \
  -f null - 2>"$MEASURE_LOG"

AUDIO_FILTER=$(python3 - "$MEASURE_LOG" "$LOUDNESS_TARGET_I" "$LOUDNESS_TARGET_LRA" "$LOUDNESS_TARGET_TP" <<'PY'
import json, re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
target_i, target_lra, target_tp = sys.argv[2:5]
blocks = re.findall(r'\{\s*"input_i".*?\}', text, flags=re.S)
if not blocks:
    raise SystemExit("Unable to read loudnorm measurement JSON from first pass")
data = json.loads(blocks[-1])
required = ["input_i", "input_tp", "input_lra", "input_thresh", "target_offset"]
for key in required:
    value = str(data.get(key, ""))
    if not value or value.lower() in {"inf", "+inf", "-inf", "nan"}:
        raise SystemExit(f"Invalid loudness measurement {key}={value!r}")
print(
    f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:"
    f"measured_I={data['input_i']}:measured_LRA={data['input_lra']}:"
    f"measured_TP={data['input_tp']}:measured_thresh={data['input_thresh']}:"
    f"offset={data['target_offset']}:linear=true:print_format=summary,"
    "aresample=48000:first_pts=0"
)
PY
)

VIDEO_FILTER='scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p'
VIDEO_SIGNATURE=$(ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt \
  -of json "$INPUT" | jq -r '.streams[0] | [.codec_name, (.width|tostring), (.height|tostring), .r_frame_rate, .pix_fmt] | join("|")')

COMMON_AUDIO=(-c:a aac -b:a 128k -ar 48000 -ac 2)
if [[ "$VIDEO_SIGNATURE" == "h264|1280|720|30/1|yuv420p" ]]; then
  # Existing library media is already video-normalized. Copy video losslessly and
  # touch only audio, making whole-library loudness migration inexpensive.
  ffmpeg -hide_banner -nostdin -y -loglevel warning \
    -i "$INPUT" -map 0:v:0 -map 0:a:0 \
    -c:v copy "${COMMON_AUDIO[@]}" -af "$AUDIO_FILTER" \
    -shortest -movflags +faststart -map_metadata -1 "$TMP_OUTPUT"
else
  ffmpeg -hide_banner -nostdin -y -loglevel warning \
    -i "$INPUT" -map 0:v:0 -map 0:a:0 \
    -vf "$VIDEO_FILTER" \
    -c:v libx264 -preset veryfast -profile:v high -level 4.0 \
    -b:v 4000k -maxrate 4000k -bufsize 8000k \
    -g 60 -keyint_min 60 -sc_threshold 0 -pix_fmt yuv420p -threads 2 \
    "${COMMON_AUDIO[@]}" -af "$AUDIO_FILTER" \
    -shortest -movflags +faststart -map_metadata -1 "$TMP_OUTPUT"
fi

# Verify the encoded result before it can replace or enter the playlist.
ffmpeg -hide_banner -nostdin -v info -i "$TMP_OUTPUT" -map 0:a:0 -vn \
  -af "loudnorm=I=${LOUDNESS_TARGET_I}:LRA=${LOUDNESS_TARGET_LRA}:TP=${LOUDNESS_TARGET_TP}:print_format=json" \
  -f null - 2>"$VERIFY_LOG"

PROFILE_JSON=$(python3 - "$VERIFY_LOG" "$PROFILE_VERSION" "$LOUDNESS_TARGET_I" "$LOUDNESS_TARGET_LRA" "$LOUDNESS_TARGET_TP" "$LOUDNESS_TOLERANCE_LU" "$MAX_POST_TRUE_PEAK" <<'PY'
import json, math, re, sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
profile = sys.argv[2]
target_i = float(sys.argv[3])
target_lra = float(sys.argv[4])
target_tp = float(sys.argv[5])
tolerance = float(sys.argv[6])
max_tp = float(sys.argv[7])
blocks = re.findall(r'\{\s*"input_i".*?\}', text, flags=re.S)
if not blocks:
    raise SystemExit("Unable to read loudness verification JSON")
data = json.loads(blocks[-1])
measured_i = float(data["input_i"])
measured_tp = float(data["input_tp"])
measured_lra = float(data["input_lra"])
if not math.isfinite(measured_i) or abs(measured_i - target_i) > tolerance:
    raise SystemExit(f"Integrated loudness verification failed: {measured_i:.2f} LUFS")
if not math.isfinite(measured_tp) or measured_tp > max_tp:
    raise SystemExit(f"True-peak verification failed: {measured_tp:.2f} dBTP")
print(json.dumps({
    "profile": profile,
    "target_i_lufs": target_i,
    "target_lra_lu": target_lra,
    "target_tp_dbtp": target_tp,
    "measured_i_lufs": measured_i,
    "measured_lra_lu": measured_lra,
    "measured_tp_dbtp": measured_tp,
}, sort_keys=True))
PY
)

mv -f "$TMP_OUTPUT" "$OUTPUT"
SHA256=$(sha256sum "$OUTPUT" | awk '{print $1}')
MARKER="${OUTPUT}.audio-profile.json"
python3 - "$MARKER" "$SHA256" "$PROFILE_JSON" <<'PY'
import json, sys, time
from pathlib import Path

path = Path(sys.argv[1])
sha = sys.argv[2]
data = json.loads(sys.argv[3])
data["sha256"] = sha
data["normalized_at_epoch"] = int(time.time())
tmp = path.with_suffix(path.suffix + ".partial")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
tmp.replace(path)
PY

trap - EXIT
rm -f "$MEASURE_LOG" "$VERIFY_LOG"
printf 'Normalized audio profile %s: %s\n' "$PROFILE_VERSION" "$OUTPUT"
printf '%s\n' "$PROFILE_JSON"
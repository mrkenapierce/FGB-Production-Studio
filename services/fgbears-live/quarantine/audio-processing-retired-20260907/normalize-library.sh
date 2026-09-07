#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: normalize-library.sh INPUT [OUTPUT]

Standardizes one owned/authorized episode for the 24/7 FGB relay and applies
OFFLINE speech mastering followed by two-pass loudness normalization. The live
encoder and platform relays do not perform audio DSP; they copy the mastered AAC.

Audio profile: fgb-podcast-v2-mastered
  cleanup: 70 Hz high-pass + 15.5 kHz low-pass
  tonal shaping: gentle low-mid reduction + speech-presence lift
  dynamics: conservative de-essing + 2.25:1 RMS compression
  final target: -14 LUFS integrated, -1.5 dBTP, LRA 11
  delivery: AAC 192 kb/s, 48 kHz, stereo
USAGE
}

[[ $# -ge 1 && $# -le 2 ]] || { usage >&2; exit 64; }
INPUT=$1
[[ -f "$INPUT" ]] || { echo "Input does not exist: $INPUT" >&2; exit 66; }

MEDIA_DIR=${MEDIA_DIR:-/srv/fgbears-live/media}
OUTPUT=${2:-"$MEDIA_DIR/$(basename "${INPUT%.*}").mp4"}
[[ "$INPUT" != "$OUTPUT" ]] || { echo "Input and output must be different paths." >&2; exit 64; }
mkdir -p "$(dirname "$OUTPUT")"

PROFILE_VERSION=${FGB_AUDIO_PROFILE_VERSION:-fgb-podcast-v2-mastered}
LOUDNESS_TARGET_I=${FGB_LOUDNESS_TARGET_I:--14}
LOUDNESS_TARGET_LRA=${FGB_LOUDNESS_TARGET_LRA:-11}
LOUDNESS_TARGET_TP=${FGB_LOUDNESS_TARGET_TP:--1.5}
LOUDNESS_TOLERANCE_LU=${FGB_LOUDNESS_TOLERANCE_LU:-0.8}
MAX_POST_TRUE_PEAK=${FGB_MAX_POST_TRUE_PEAK:--1.0}
MASTERING_CHAIN=${FGB_MASTERING_CHAIN:-'highpass=f=70:p=2,lowpass=f=15500:p=2,equalizer=f=180:t=q:w=0.9:g=-1.5,equalizer=f=3200:t=q:w=0.8:g=1.25,deesser=i=0.15:m=0.35:f=0.5,acompressor=threshold=0.125:ratio=2.25:attack=12:release=180:makeup=1.12:knee=2.5:link=maximum:detection=rms'}

FILTER_LIST=$(ffmpeg -hide_banner -filters 2>/dev/null)
for filter in highpass lowpass equalizer deesser acompressor loudnorm aresample; do
  grep -Eq "[[:space:]]${filter}[[:space:]]" <<<"$FILTER_LIST" || { echo "Required FFmpeg audio filter is unavailable: $filter" >&2; exit 69; }
done

TMP_OUTPUT="${OUTPUT%.mp4}.partial.mp4"
MEASURE_LOG=$(mktemp)
VERIFY_LOG=$(mktemp)
trap 'rm -f "$TMP_OUTPUT" "$MEASURE_LOG" "$VERIFY_LOG"' EXIT
ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 "$INPUT" | grep -q . || { echo "Input has no audio stream" >&2; exit 65; }
ffmpeg -hide_banner -nostdin -v info -i "$INPUT" -map 0:a:0 -vn -af "${MASTERING_CHAIN},loudnorm=I=${LOUDNESS_TARGET_I}:LRA=${LOUDNESS_TARGET_LRA}:TP=${LOUDNESS_TARGET_TP}:print_format=json" -f null - 2>"$MEASURE_LOG"
LOUDNORM_FILTER=$(python3 - "$MEASURE_LOG" "$LOUDNESS_TARGET_I" "$LOUDNESS_TARGET_LRA" "$LOUDNESS_TARGET_TP" <<'PY'
import json,re,sys
from pathlib import Path
text=Path(sys.argv[1]).read_text(encoding='utf-8',errors='replace')
target_i,target_lra,target_tp=sys.argv[2:5]
data=json.loads(re.findall(r'\{\s*"input_i".*?\}',text,re.S)[-1])
print(f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:measured_I={data['input_i']}:measured_LRA={data['input_lra']}:measured_TP={data['input_tp']}:measured_thresh={data['input_thresh']}:offset={data['target_offset']}:linear=true:print_format=summary")
PY
)
AUDIO_FILTER="${MASTERING_CHAIN},${LOUDNORM_FILTER},aresample=48000:first_pts=0"
VIDEO_SIGNATURE=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt -of json "$INPUT" | jq -r '.streams[0] | [.codec_name, (.width|tostring), (.height|tostring), .r_frame_rate, .pix_fmt] | join("|")')
COMMON_AUDIO=(-c:a aac -b:a 192k -ar 48000 -ac 2)
if [[ "$VIDEO_SIGNATURE" == "h264|1280|720|30/1|yuv420p" ]]; then
  ffmpeg -hide_banner -nostdin -y -loglevel warning -i "$INPUT" -map 0:v:0 -map 0:a:0 -c:v copy "${COMMON_AUDIO[@]}" -af "$AUDIO_FILTER" -shortest -movflags +faststart -map_metadata -1 "$TMP_OUTPUT"
else
  ffmpeg -hide_banner -nostdin -y -loglevel warning -i "$INPUT" -map 0:v:0 -map 0:a:0 -vf 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p' -c:v libx264 -preset veryfast -profile:v high -level 4.0 -b:v 4000k -maxrate 4000k -bufsize 8000k -g 60 -keyint_min 60 -sc_threshold 0 -pix_fmt yuv420p -threads 2 "${COMMON_AUDIO[@]}" -af "$AUDIO_FILTER" -shortest -movflags +faststart -map_metadata -1 "$TMP_OUTPUT"
fi
mv -f "$TMP_OUTPUT" "$OUTPUT"

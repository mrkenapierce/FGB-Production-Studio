#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR=${1:-${MEDIA_DIR:-/srv/fgbears-live/media}}
[[ -d "$MEDIA_DIR" ]] || { echo "Media directory does not exist: $MEDIA_DIR" >&2; exit 66; }

PROFILE_VERSION=${FGB_AUDIO_PROFILE_VERSION:-fgb-podcast-v1}
LOUDNESS_TARGET_I=${FGB_LOUDNESS_TARGET_I:--14}
LOUDNESS_TOLERANCE_LU=${FGB_LOUDNESS_TOLERANCE_LU:-0.8}
MAX_POST_TRUE_PEAK=${FGB_MAX_POST_TRUE_PEAK:--1.0}

failures=0
count=0
while IFS= read -r -d '' file; do
  count=$((count + 1))
  video=$(ffprobe -v error -select_streams v:0 \
    -show_entries stream=codec_name,width,height,r_frame_rate,pix_fmt \
    -of json "$file" | jq -r '.streams[0] | [.codec_name, (.width|tostring), (.height|tostring), .r_frame_rate, .pix_fmt] | join("|")')
  audio=$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels \
    -of json "$file" | jq -r '.streams[0] | [.codec_name, .sample_rate, (.channels|tostring)] | join("|")')

  marker="${file}.audio-profile.json"
  marker_ok=false
  if [[ -s "$marker" ]]; then
    expected_sha=$(sha256sum "$file" | awk '{print $1}')
    if jq -e \
      --arg profile "$PROFILE_VERSION" \
      --arg sha "$expected_sha" \
      --argjson target "$LOUDNESS_TARGET_I" \
      --argjson tolerance "$LOUDNESS_TOLERANCE_LU" \
      --argjson maxTp "$MAX_POST_TRUE_PEAK" \
      '.profile == $profile and .sha256 == $sha and
       ((.measured_i_lufs - $target) | if . < 0 then -. else . end) <= $tolerance and
       .measured_tp_dbtp <= $maxTp' "$marker" >/dev/null; then
      marker_ok=true
    fi
  fi

  if [[ "$video" != "h264|1280|720|30/1|yuv420p" || "$audio" != "aac|48000|2" || "$marker_ok" != true ]]; then
    echo "INVALID: $file" >&2
    echo "  video=$video" >&2
    echo "  audio=$audio" >&2
    if [[ "$marker_ok" != true ]]; then
      echo "  audio_profile=missing_or_invalid (required=$PROFILE_VERSION)" >&2
    fi
    failures=$((failures + 1))
  else
    measured_i=$(jq -r '.measured_i_lufs' "$marker")
    measured_tp=$(jq -r '.measured_tp_dbtp' "$marker")
    echo "OK: $file audio_profile=$PROFILE_VERSION I=${measured_i}LUFS TP=${measured_tp}dBTP"
  fi
done < <(find "$MEDIA_DIR" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -zV)

[[ $count -gt 0 ]] || { echo "No MP4 files found in $MEDIA_DIR" >&2; exit 65; }
[[ $failures -eq 0 ]] || exit 1
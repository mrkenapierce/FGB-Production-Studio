#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR=${1:-${MEDIA_DIR:-/srv/fgbears-live/media}}
[[ -d "$MEDIA_DIR" ]] || { echo "Media directory does not exist: $MEDIA_DIR" >&2; exit 66; }

PROFILE_VERSION=${FGB_AUDIO_PROFILE_VERSION:-fgb-clean-static-v3}
MAX_POST_TRUE_PEAK=${FGB_MAX_POST_TRUE_PEAK:--1.5}
MAX_LRA_DELTA=${FGB_MAX_LRA_DELTA:-0.6}

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
      --argjson maxTp "$MAX_POST_TRUE_PEAK" \
      --argjson maxLraDelta "$MAX_LRA_DELTA" \
      '.profile == $profile and
       .quality_verified == true and
       .processing_mode == "static_gain_only" and
       .dynamic_processing == false and
       .processing_chain == ["constant_gain","aresample_48000","stereo_delivery","aac_encode_256k"] and
       .audio_codec == "aac" and
       .audio_bitrate_kbps == 256 and
       .sample_rate_hz == 48000 and
       .channels == 2 and
       .sha256 == $sha and
       .target_i_lufs == -16 and
       .output_metrics.tp_dbtp <= $maxTp and
       (((.output_metrics.lra_lu - .source_metrics.lra_lu) | if . < 0 then -. else . end) <= $maxLraDelta) and
       (.source_kind == "original_master" or .source_kind == "retained_pre_v2" or .source_kind == "new_original")' "$marker" >/dev/null; then
      marker_ok=true
    fi
  fi

  if [[ "$video" != "h264|1280|720|30/1|yuv420p" || "$audio" != "aac|48000|2" || "$marker_ok" != true ]]; then
    echo "INVALID: $file" >&2
    echo "  video=$video" >&2
    echo "  audio=$audio" >&2
    [[ "$marker_ok" == true ]] || echo "  audio_profile=missing_or_invalid (required=$PROFILE_VERSION static_gain_only)" >&2
    failures=$((failures + 1))
  else
    source_i=$(jq -r '.source_metrics.i_lufs' "$marker")
    output_i=$(jq -r '.output_metrics.i_lufs' "$marker")
    output_tp=$(jq -r '.output_metrics.tp_dbtp' "$marker")
    gain=$(jq -r '.static_gain_db' "$marker")
    echo "OK: $file profile=$PROFILE_VERSION source_I=${source_i}LUFS gain=${gain}dB output_I=${output_i}LUFS TP=${output_tp}dBTP"
  fi
done < <(find "$MEDIA_DIR" -maxdepth 1 -type f -name '*.mp4' -print0 | sort -zV)

[[ $count -gt 0 ]] || { echo "No MP4 files found in $MEDIA_DIR" >&2; exit 65; }
[[ $failures -eq 0 ]] || exit 1

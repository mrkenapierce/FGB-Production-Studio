#!/usr/bin/env bash
set -Eeuo pipefail

[[ $# -ge 1 && $# -le 2 ]] || { echo "Usage: normalize-resilient.sh INPUT [OUTPUT]" >&2; exit 64; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ -x "$SCRIPT_DIR/normalize-library.sh" ]]; then
  BASE_NORMALIZER="$SCRIPT_DIR/normalize-library.sh"
elif [[ -x /usr/local/bin/fgbears-normalize ]]; then
  BASE_NORMALIZER=/usr/local/bin/fgbears-normalize
else
  echo "Base FGB normalizer not found" >&2
  exit 69
fi

# Standard path first. Most episodes should pass without dynamic processing.
if bash "$BASE_NORMALIZER" "$@"; then
  exit 0
fi

# Some AAC sources exhibit large intersample overshoot after encoding even when
# loudnorm's nominal TP target is lower. Retry entirely OFFLINE in dynamic mode
# with progressively larger true-peak headroom. The verifier inside the base
# normalizer remains authoritative: -14 LUFS +/-0.8 LU and <= -1.0 dBTP.
DYNAMIC_NORMALIZER=$(mktemp)
trap 'rm -f "$DYNAMIC_NORMALIZER"' EXIT
sed 's/linear=true:print_format=summary/linear=false:print_format=summary/' "$BASE_NORMALIZER" > "$DYNAMIC_NORMALIZER"
chmod +x "$DYNAMIC_NORMALIZER"

for tp in -3.0 -6.0 -9.0; do
  echo "Retrying offline dynamic normalization with target TP=${tp} dBTP" >&2
  if env FGB_LOUDNESS_TARGET_TP="$tp" bash "$DYNAMIC_NORMALIZER" "$@"; then
    exit 0
  fi
done

echo "All resilient normalization attempts failed" >&2
exit 1

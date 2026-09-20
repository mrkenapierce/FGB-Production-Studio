#!/usr/bin/env bash
set -Eeuo pipefail

CONTROL_BASE_URL=${CONTROL_BASE_URL:-https://raw.githubusercontent.com/mrkenapierce/FGB-Production-Studio/main}
CONTROL_ROOT=${CONTROL_ROOT:-/srv/fgbears-live/control}
CURRENT_DIR="$CONTROL_ROOT/current"
STAGING_DIR=$(mktemp -d "$CONTROL_ROOT/staging.XXXXXX")
trap 'rm -rf "$STAGING_DIR"' EXIT

command -v curl >/dev/null || { echo "curl is required" >&2; exit 69; }
command -v jq >/dev/null || { echo "jq is required" >&2; exit 69; }

schedule_rel=services/fgbears-live/control/schedule.json
schedule_path="$STAGING_DIR/$schedule_rel"
mkdir -p "$(dirname "$schedule_path")"
curl --fail --silent --show-error --location "$CONTROL_BASE_URL/$schedule_rel" -o "$schedule_path"

mapfile -t assets < <(jq -r '[.fallback_asset, (.items[].asset)] | unique[]' "$schedule_path")
for rel in "${assets[@]}"; do
  [[ -n "$rel" && "$rel" != "null" ]] || continue
  case "$rel" in
    services/fgbears-live/control/*) ;;
    *) echo "Refusing asset outside control tree: $rel" >&2; exit 65 ;;
  esac
  destination="$STAGING_DIR/$rel"
  mkdir -p "$(dirname "$destination")"
  curl --fail --silent --show-error --location "$CONTROL_BASE_URL/$rel" -o "$destination"
done

validator=/opt/fgbears-live/bin/validate-control.py
[[ -x "$validator" || -f "$validator" ]] || validator="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/validate-control.py"
python3 "$validator" "$schedule_path" "$STAGING_DIR"

mkdir -p "$CONTROL_ROOT"
next="$CONTROL_ROOT/next"
rm -rf "$next"
mv "$STAGING_DIR" "$next"
trap - EXIT

if [[ -d "$CURRENT_DIR" ]]; then
  rm -rf "$CONTROL_ROOT/previous"
  mv "$CURRENT_DIR" "$CONTROL_ROOT/previous"
fi
mv "$next" "$CURRENT_DIR"

echo "Control package synchronized and validated. No stream service was restarted."

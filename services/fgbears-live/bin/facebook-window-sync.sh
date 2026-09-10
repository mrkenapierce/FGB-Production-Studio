#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

case "${FACEBOOK_RELAY_ENABLED:-0}" in
  1|true|TRUE|yes|YES|on|ON) ;;
  *) systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true; exit 0 ;;
esac

# Alternate 10-minute blocks continuously in America/Chicago, anchored on :05:
# LIVE : :05-:14, :25-:34, :45-:54
# OFF  : :15-:24, :35-:44, :55-:04
minute=$(TZ=America/Chicago date +%M)
minute=$((10#$minute))
shifted=$(((minute + 55) % 60))
slot=$((shifted / 10))

if (( slot % 2 == 0 )); then
  if ! systemctl is-active --quiet fgbears-facebook-relay.service; then
    systemctl reset-failed fgbears-facebook-relay.service || true
    systemctl start fgbears-facebook-relay.service
  fi
else
  systemctl stop fgbears-facebook-relay.service >/dev/null 2>&1 || true
fi

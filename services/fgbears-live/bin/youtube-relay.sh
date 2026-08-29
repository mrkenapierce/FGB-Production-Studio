#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE=${ENV_FILE:-/etc/fgbears-live/stream.env}
[[ -r "$ENV_FILE" ]] || { echo "Missing environment file: $ENV_FILE" >&2; exit 78; }
# shellcheck disable=SC1090
source "$ENV_FILE"

ROUTER=/opt/fgbears-live/bin/youtube-stream-router.py
CARD=${FGB_YOUTUBE_TRIVIA_CARD_H264:-/opt/fgbears-live/assets/youtube-rumble-trivia.h264}
LEGACY=/opt/fgbears-live/bin/youtube-relay-legacy.sh
: "${FGB_YOUTUBE_PACKET_ROUTER_ENABLE:=1}"

if [[ "$FGB_YOUTUBE_PACKET_ROUTER_ENABLE" == "1" \
      && -r "$ROUTER" \
      && -r "$CARD" \
      && -x /usr/bin/python3 \
      && -x /usr/bin/gst-launch-1.0 ]]; then
  echo "Starting low-CPU YouTube stream router (legacy copy relay armed as fallback)." >&2
  set +e
  /usr/bin/python3 "$ROUTER" --card "$CARD"
  rc=$?
  set -e

  # A clean exit is a normal systemd stop. Do not resurrect the relay while the
  # unit is intentionally being stopped.
  if [[ $rc -eq 0 || $rc -eq 130 || $rc -eq 143 ]]; then
    exit "$rc"
  fi
  echo "YouTube stream router exited rc=$rc; falling back to safe copy relay." >&2
else
  echo "YouTube stream router unavailable/disabled; using safe copy relay." >&2
fi

# Full installs preserve repository blob modes, and newly created fallback
# scripts can arrive as 0644. Invoke through Bash so fallback remains usable
# even when the file itself lacks an execute bit.
exec /usr/bin/bash "$LEGACY"

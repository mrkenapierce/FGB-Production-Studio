#!/usr/bin/env bash
set -Eeuo pipefail

# INCIDENT QUARANTINE
# This exact Episode 034 candidate passed structural validation but was twice
# rejected by the user after live playback. It must never be redeployed.
REJECTED_SHA=c04e4fa32a5acc4200c2ef88e8bf43f7618998768ad8c58a716f7869a35a9e7a
printf 'BLOCKED: user-rejected Episode 034 candidate %s may not be deployed.\n' "$REJECTED_SHA" >&2
printf 'Use a new source, a new hash, and a separately reviewed deployment path.\n' >&2
exit 64

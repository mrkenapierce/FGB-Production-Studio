#!/usr/bin/env bash
# FGB-only recovery for a SIGTRAP/“Aw, Snap!” renderer; never restarts FFmpeg or CNT.
set -euo pipefail
exec 9>/run/lock/fgb-browser-guard.lock
flock -n 9 || exit 0
CONTAINER=fgb-transport-youtube-1
PROBE_HOST=/usr/local/libexec/fgb-renderer-probe.py
PROBE_CONTAINER=/tmp/fgb-renderer-probe.py
STATE_DIR=/var/lib/fgb-browser-guard
STATE_FILE="$STATE_DIR/state"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
failures=0
last_attempt=0
window_start=0
attempts=0
[[ ! -f "$STATE_FILE" ]] || source "$STATE_FILE"
for value in "$failures" "$last_attempt" "$window_start" "$attempts"; do
  [[ "$value" =~ ^[0-9]+$ ]] || { echo 'Invalid FGB browser guard state'; exit 2; }
done
save() {
  local tmp
  tmp=$(mktemp "$STATE_DIR/state.XXXXXX")
  printf 'failures=%s\nlast_attempt=%s\nwindow_start=%s\nattempts=%s\n' \
    "$failures" "$last_attempt" "$window_start" "$attempts" >"$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$STATE_FILE"
}
say() { echo "$(date -u +%FT%TZ) FGB_BROWSER_GUARD $*"; }
if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != true ]]; then
  say "FGB_CONTAINER_UNAVAILABLE no action"
  exit 0
fi
# A Docker recreation discards /tmp; restage the probe inside FGB only.
if ! docker exec "$CONTAINER" test -f "$PROBE_CONTAINER" >/dev/null 2>&1; then
  docker cp "$PROBE_HOST" "$CONTAINER:$PROBE_CONTAINER" >/dev/null
fi
probe() { docker exec "$CONTAINER" python3 "$PROBE_CONTAINER" 2>&1; }
if output=$(probe); then
  if (( failures > 0 )); then say "RECOVERED_WITHOUT_ACTION failures_before=$failures"; fi
  failures=0
  save
  exit 0
fi
failures=$((failures + 1))
say "UNHEALTHY consecutive=$failures detail=$(printf '%.240s' "$output")"
save
# Three bad renderer evaluations on separate systemd timer invocations.
(( failures >= 3 )) || exit 0
now=$(date +%s)
if (( now - window_start >= 3600 )); then window_start=$now; attempts=0; fi
if (( now - last_attempt < 180 )); then
  say "COOLDOWN remaining=$((180-(now-last_attempt)))s"
  save
  exit 0
fi
if (( attempts >= 3 )); then
  say 'RECOVERY_BUDGET_EXHAUSTED 3 attempts/hour; investigation required'
  save
  exit 1
fi
last_attempt=$now
attempts=$((attempts + 1))
save
before_container=$(docker inspect -f '{{.Id}}' "$CONTAINER")
before_restarts=$(docker inspect -f '{{.RestartCount}}' "$CONTAINER")
before_encoder=$(docker exec "$CONTAINER" sh -lc 'pgrep -o ffmpeg' || true)
[[ "$before_encoder" =~ ^[0-9]+$ ]] || { say 'ENCODER_NOT_RUNNING refuse page recovery'; exit 1; }
say "PAGE_ONLY_RECOVERY_BEGIN attempt=$attempts/hour"
# Reuses tested production operator repair; preserves live FFmpeg and container.
if bash /opt/fgb-transport/refresh-browser.sh >/tmp/fgb-browser-guard-last-repair.log 2>&1; then
  say 'CHROMIUM_TAB_REPLACED'
else
  say 'TAB_REPLACEMENT_FAILED checking isolated Chromium recovery'
  # Parent Chromium only; transport supervisor brings its browser back.
  docker exec "$CONTAINER" sh -lc '
    pid=$(pgrep -o chromium || true)
    case "$pid" in ""|0|*[!0-9]*) exit 1;; esac
    kill -TERM "$pid"
  ' || { say 'ISOLATED_CHROMIUM_RECOVERY_UNAVAILABLE'; exit 1; }
  sleep 12
fi
after_container=$(docker inspect -f '{{.Id}}' "$CONTAINER")
after_restarts=$(docker inspect -f '{{.RestartCount}}' "$CONTAINER")
after_encoder=$(docker exec "$CONTAINER" sh -lc 'pgrep -o ffmpeg' || true)
if [[ "$after_container" != "$before_container" || "$after_restarts" != "$before_restarts" || "$after_encoder" != "$before_encoder" ]]; then
  say 'ERROR_ENCODER_CONTINUITY_CHANGED investigate immediately'
  exit 1
fi
if output=$(probe); then
  failures=0
  save
  say 'PAGE_ONLY_RECOVERY_SUCCESS encoder_unchanged=yes container_unchanged=yes'
else
  say "PAGE_ONLY_RECOVERY_FAILED detail=$(printf '%.240s' "$output")"
  exit 1
fi

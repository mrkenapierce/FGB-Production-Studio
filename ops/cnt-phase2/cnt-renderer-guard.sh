#!/usr/bin/env bash
set -euo pipefail
exec 9>/run/lock/epic-cnt-renderer.lock
flock -n 9 || exit 0
c=epic-cnt-capture
state=/var/lib/epic-cnt-renderer
mkdir -p "$state"
[[ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" == true ]] || exit 0
for file in cnt-renderer-probe.py cnt-page-recovery.py; do
  docker cp "/usr/local/libexec/$file" "$c:/tmp/$file" >/dev/null
done
if timeout 12 docker exec "$c" python3 /tmp/cnt-renderer-probe.py; then
  echo 0 > "$state/failures"
  date -u +%FT%TZ > "$state/last-healthy"
  exit 0
fi
failures=$(cat "$state/failures" 2>/dev/null || echo 0)
[[ "$failures" =~ ^[0-9]+$ ]] || failures=0
failures=$((failures+1))
echo "$failures" > "$state/failures"
(( failures >= 3 )) || exit 0
now=$(date +%s)
last=$(cat "$state/last-attempt" 2>/dev/null || echo 0)
[[ "$last" =~ ^[0-9]+$ ]] || last=0
(( now-last >= 180 )) || { echo CNT_RECOVERY_COOLDOWN; exit 0; }
touch "$state/attempts"
awk -v cutoff="$((now-3600))" '$1>cutoff' "$state/attempts" > "$state/recent"
mv "$state/recent" "$state/attempts"
(( $(wc -l < "$state/attempts") < 3 )) || { echo CNT_RECOVERY_BUDGET_EXHAUSTED; exit 1; }
before=$(docker exec "$c" pgrep -o ffmpeg)
fgb_before=$(docker inspect -f '{{.State.StartedAt}}:{{.RestartCount}}' fgb-transport-youtube-1)
[[ "$before" =~ ^[0-9]+$ ]] || exit 1
echo "$now" > "$state/last-attempt"
echo "$now" >> "$state/attempts"
timeout 45 docker exec "$c" python3 /tmp/cnt-page-recovery.py
[[ "$(docker exec "$c" pgrep -o ffmpeg)" == "$before" ]]
[[ "$(docker inspect -f '{{.State.StartedAt}}:{{.RestartCount}}' fgb-transport-youtube-1)" == "$fgb_before" ]]
echo 0 > "$state/failures"
date -u +%FT%TZ > "$state/last-healthy"
echo CNT_RECOVERY_VERIFIED_ENCODER_UNCHANGED_FGB_UNCHANGED

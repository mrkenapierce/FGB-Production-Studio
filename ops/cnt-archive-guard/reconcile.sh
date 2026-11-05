#!/usr/bin/env bash
# CNT-only archive worker network-namespace reconciler.
# Never restarts the capture encoder, FGB, or the Docker daemon.
set -euo pipefail
umask 077
exec 9>/run/lock/cnt-archive-network-reconcile.lock
flock -n 9 || exit 0

cd /opt/cnt-transport
d() { docker "$@"; }
active() { d inspect --format '{{.State.Running}}' "$1" 2>/dev/null; }
if [ "$(active epic-cnt-capture || true)" != true ]; then exit 0; fi
if [ "$(active epic-cnt-archive-worker || true)" != true ]; then exit 0; fi
capture_id=$(d inspect --format '{{.Id}}' epic-cnt-capture)
capture_start=$(d inspect --format '{{.State.StartedAt}}' epic-cnt-capture)
capture_health=$(d inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' epic-cnt-capture)
if [ "$capture_health" != healthy ]; then exit 0; fi
capture_age=$(( $(date -u +%s) - $(date -u -d "$capture_start" +%s) ))
if [ "$capture_age" -lt 60 ]; then exit 0; fi
worker_net=$(d inspect --format '{{.HostConfig.NetworkMode}}' epic-cnt-archive-worker)
if [ "$worker_net" = "container:$capture_id" ]; then exit 0; fi
case "$worker_net" in
  container:*) ;;
  *) echo 'CNT archive guard: unknown worker network mode; refusing changes' >&2; exit 1 ;;
esac

# Permit only the deployed CNT phase2 service/mounts.
[ -f docker-compose.phase2.yml ] || exit 1
d compose -p epic-cnt-transport -f docker-compose.phase2.yml config --format json | python3 -c '
import json,sys
s=json.load(sys.stdin)["services"]["archive_worker"]
assert s.get("network_mode")=="service:cnt"
assert any(v.get("target")=="/cnt-archive" for v in s.get("volumes",[]))
assert any(v.get("target")=="/run/secrets/cnt_archive_key" for v in s.get("volumes",[]))
'
archive_dir=$(d inspect --format '{{range .Mounts}}{{if eq .Destination "/cnt-archive"}}{{.Source}}{{end}}{{end}}' epic-cnt-archive-worker)
test -n "$archive_dir"
test -s "$archive_dir/state/air-observer.json"
test -s "$archive_dir/state/chrome.log"
d exec epic-cnt-archive-worker test -s /run/secrets/cnt_archive_key

# Avoid repeated disruptive retries if the daemon or service is unhealthy.
mkdir -p -m 0700 /var/lib/cnt-archive-network-guard
stamp=/var/lib/cnt-archive-network-guard/last_attempt
now=$(date -u +%s)
if [ -s "$stamp" ]; then
  read -r last < "$stamp" || last=0
  case "$last" in ''|*[!0-9]*) last=0 ;; esac
  if [ "$((now-last))" -lt 300 ]; then exit 0; fi
fi
printf '%s\n' "$now" > "$stamp.tmp"
mv -f "$stamp.tmp" "$stamp"

echo 'CNT archive guard: stale capture namespace detected; recreating archive_worker only'
d compose -p epic-cnt-transport -f docker-compose.phase2.yml up -d --no-deps --no-build --force-recreate archive_worker
actual_capture=$(d inspect --format '{{.Id}}' epic-cnt-capture)
actual_worker_net=$(d inspect --format '{{.HostConfig.NetworkMode}}' epic-cnt-archive-worker)
actual_archive_dir=$(d inspect --format '{{range .Mounts}}{{if eq .Destination "/cnt-archive"}}{{.Source}}{{end}}{{end}}' epic-cnt-archive-worker)
[ "$actual_capture" = "$capture_id" ] || { echo 'CNT archive guard: capture changed during repair' >&2; exit 1; }
[ "$actual_worker_net" = "container:$capture_id" ] || { echo 'CNT archive guard: worker failed rebind check' >&2; exit 1; }
[ "$actual_archive_dir" = "$archive_dir" ] || { echo 'CNT archive guard: archive mount changed unexpectedly' >&2; exit 1; }
echo 'CNT archive guard: reporter network rebound; capture and archive storage unchanged'

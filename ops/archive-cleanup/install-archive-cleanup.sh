#!/usr/bin/env bash
# Installs the receipt-gated cleanup for ONE channel. Never deletes anything,
# never touches streams/encoders, never enables destructive mode.
#   sudo ./install-archive-cleanup.sh fgb            # install + one dry run
#   sudo ./install-archive-cleanup.sh fgb --timer    # also start 15-min timer
# The timer stays dry-run until the env file sets DRY_RUN=false AND
# CLEANUP_CONFIRM_DELETE=yes, which must be edited by hand after review.
set -euo pipefail
ch="${1:-}"; [ "$ch" = fgb ] || [ "$ch" = cnt ] || { echo "usage: $0 fgb|cnt [--timer]" >&2; exit 2; }
here="$(cd "$(dirname "$0")" && pwd)"
install -d -m 755 /opt/epic-archive-cleanup
install -m 755 "$here/archive-cleanup.py" /opt/epic-archive-cleanup/archive-cleanup.py
install -d -m 700 /etc/epic-archive-cleanup
env=/etc/epic-archive-cleanup/$ch.env
if [ ! -f "$env" ]; then install -m 600 "$here/systemd/$ch.env.example" "$env"; echo "Created $env: add the $ch secret, then rerun."; exit 0; fi
grep -q '^DRY_RUN=true' "$env" || echo "WARNING: $env is not in dry-run mode"
install -m 644 "$here/systemd/epic-archive-cleanup-$ch.service" "$here/systemd/epic-archive-cleanup-$ch.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl start "epic-archive-cleanup-$ch.service" || true
journalctl -u "epic-archive-cleanup-$ch.service" -n 40 --no-pager || true
[ "${2:-}" = --timer ] && systemctl enable --now "epic-archive-cleanup-$ch.timer"
echo "Status file: $(grep ^CLEANUP_ROOT "$env" | cut -d= -f2)/state/cleanup-status.json"

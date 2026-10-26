#!/usr/bin/env bash
# CNT rolling-buffer retention. DRY-RUN BY DEFAULT. CNT only.
#   cnt-archive-retention.sh            # inventory: KEEP/ELIGIBLE per file, no writes
#   CNT_RETENTION_APPLY=yes cnt-archive-retention.sh --apply   # delete ELIGIBLE only
#
# A rolling file is ELIGIBLE only if ALL hold:
#   * it lives directly in $CNT_ARCHIVE_DIR/rolling, is a regular non-symlink
#     live-*.ts file, and is not the newest file (still being written);
#   * its dependencies are confirmed (prompt release after discovery grace),
#     or it is unneeded general footage older than THREE hours;
#   * it is not listed in state/episode_hold or state/daily_hold;
#   * both hold files exist and are fresh (< 10 min). Missing/stale holds mean a
#     holder may be down, so NOTHING is eligible (fail safe).
# Daily videos and episodes release their hold only after the app confirms the
# YouTube upload, so retention is driven by confirmed uploads + hold policy.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# CNT_BUFFER_HOURS is retired: the ordinary fallback is exactly 10800 seconds.
args=(); [ "${1:-}" = --apply ] && args+=(--apply)
exec python3 "$here/archive-retention.py" inventory --channel cnt --root "${CNT_ARCHIVE_DIR:-/cnt-archive}" "${args[@]}"
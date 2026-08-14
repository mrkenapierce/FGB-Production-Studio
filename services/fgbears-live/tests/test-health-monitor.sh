#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REPO_ROOT=$(cd -- "$ROOT/../.." && pwd)

bash -n "$ROOT/bin/healthcheck.sh"
bash -n "$ROOT/bin/stream-status.sh"

grep -Fq 'LAG_STATUS_BIN=${FFMPEG_LAG_STATUS_BIN:-/usr/local/bin/fgbears-stream-status}' "$ROOT/bin/healthcheck.sh"
grep -Fq 'LAG_SAMPLE_SECONDS=${FFMPEG_LAG_SAMPLE_SECONDS:-20}' "$ROOT/bin/healthcheck.sh"
grep -Fq 'ENCODER_BELOW_REALTIME' "$ROOT/bin/healthcheck.sh"
grep -Fq 'Stream left running to avoid a restart loop.' "$ROOT/bin/healthcheck.sh"
grep -Fq 'OnUnitActiveSec=5min' "$ROOT/systemd/fgbears-live-health.timer"
grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$ROOT/bin/install.sh"
grep -Fq "cron: '*/5 * * * *'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
grep -Fq "'sudo /usr/local/bin/fgbears-stream-status --sample-seconds 20'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"

echo 'Scheduled local and independent encoder-lag monitoring checks passed.'

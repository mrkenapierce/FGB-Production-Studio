#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REPO_ROOT=$(cd -- "$ROOT/../.." && pwd)

bash -n "$ROOT/bin/healthcheck.sh"
bash -n "$ROOT/bin/stream-status.sh"
python3 -m py_compile "$ROOT/bin/refresh-bears-news.py"

# These are intentionally literal shell expressions in the production script.
# shellcheck disable=SC2016
grep -Fq 'LAG_STATUS_BIN=${FFMPEG_LAG_STATUS_BIN:-/usr/local/bin/fgbears-stream-status}' "$ROOT/bin/healthcheck.sh"
# shellcheck disable=SC2016
grep -Fq 'LAG_SAMPLE_SECONDS=${FFMPEG_LAG_SAMPLE_SECONDS:-20}' "$ROOT/bin/healthcheck.sh"
grep -Fq 'ENCODER_BELOW_REALTIME' "$ROOT/bin/healthcheck.sh"
grep -Fq 'Stream left running to avoid a restart loop.' "$ROOT/bin/healthcheck.sh"
grep -Fq 'OnCalendar=*:0/5' "$ROOT/systemd/fgbears-live-health.timer"
grep -Fq 'AccuracySec=1s' "$ROOT/systemd/fgbears-live-health.timer"
grep -Fq 'NEWS_REFRESH_INTERVAL_SECONDS=${BEARS_NEWS_REFRESH_INTERVAL_SECONDS:-900}' "$ROOT/bin/healthcheck.sh"
grep -Fq 'run_news_refresh' "$ROOT/bin/healthcheck.sh"
grep -Fq 'NEWS_REFRESH_STALE' "$ROOT/bin/stream-status.sh"
grep -Fq 'recover_youtube_relay' "$ROOT/bin/healthcheck.sh"
grep -Fq 'systemctl reset-failed "$YOUTUBE_RELAY_SERVICE"' "$ROOT/bin/healthcheck.sh"
grep -Fq 'isolated UDP relay without touching the primary encoder' "$ROOT/bin/healthcheck.sh"
# Relay recovery must never restart the primary program. Keep encoder restarts
# confined to guarded_restart for genuine encoder failures/progress stalls.
recover_body=$(sed -n '/^recover_youtube_relay()/,/^}/p' "$ROOT/bin/healthcheck.sh")
if grep -Fq 'systemctl restart fgbears-live.service' <<<"$recover_body"; then
  echo 'YouTube relay recovery must not restart the primary encoder.' >&2
  exit 1
fi
grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$ROOT/bin/install.sh"
grep -Fq "cron: '*/5 * * * *'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
grep -Fq "'sudo /usr/local/bin/fgbears-stream-status --sample-seconds 20'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"

echo 'Scheduled local and independent encoder/news/YouTube-relay monitoring checks passed.'

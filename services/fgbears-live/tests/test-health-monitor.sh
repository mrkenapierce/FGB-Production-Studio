#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
REPO_ROOT=$(cd -- "$ROOT/../.." && pwd)

bash -n "$ROOT/bin/healthcheck.sh"
bash -n "$ROOT/bin/stream-status.sh"
bash -n "$ROOT/bin/youtube-audio-watchdog-owner-aware.sh"
bash -n "$ROOT/bin/youtube-audio-watchdog.sh"
python3 -m py_compile "$ROOT/bin/refresh-bears-news.py"

# Shared-master health remains a five-minute local guard for progress, lag and
# independent news refresh only.
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

# Destination-specific ownership/recovery and deep audio analysis must not leak
# back into the master health checker; that would create competing supervisors
# and duplicate raw-audio analysis.
if grep -Eq 'recover_youtube_relay|YOUTUBE_RELAY_SERVICE|FGB_AUDIO_HEALTH_BIN|run_audio_check' "$ROOT/bin/healthcheck.sh"; then
  echo 'Master healthcheck contains destination-specific YouTube/audio recovery.' >&2
  exit 1
fi

# YouTube transport/format ownership is checked each minute, while the expensive
# raw loopback/decode analysis is shared between primary/fallback at 15 minutes.
grep -Fq 'OnUnitActiveSec=60s' "$ROOT/systemd/fgbears-youtube-audio-watchdog.timer"
grep -Fq 'DEEP_AUDIO_INTERVAL_SECONDS=${FGB_YOUTUBE_DEEP_AUDIO_INTERVAL_SECONDS:-900}' "$ROOT/bin/youtube-audio-watchdog-owner-aware.sh"
grep -Fq 'LAST_DEEP_AUDIO_CHECK_FILE=${FGB_YOUTUBE_DEEP_AUDIO_EPOCH_FILE:-$STATE_DIR/deep-audio-epoch}' "$ROOT/bin/youtube-audio-watchdog-owner-aware.sh"
grep -Fq 'output_audio_format_ok' "$ROOT/bin/youtube-audio-watchdog-owner-aware.sh"
grep -Fq 'rtmps_socket_ok' "$ROOT/bin/youtube-audio-watchdog-owner-aware.sh"
grep -Fq 'DEEP_AUDIO_INTERVAL_SECONDS=${FGB_YOUTUBE_DEEP_AUDIO_INTERVAL_SECONDS:-900}' "$ROOT/bin/youtube-audio-watchdog.sh"
grep -Fq 'LAST_DEEP_AUDIO_CHECK_FILE=${FGB_YOUTUBE_DEEP_AUDIO_EPOCH_FILE:-$STATE_DIR/deep-audio-epoch}' "$ROOT/bin/youtube-audio-watchdog.sh"

grep -Fq 'systemctl enable --now fgbears-live-health.timer' "$ROOT/bin/install.sh"
grep -Fq 'systemctl enable --now fgbears-youtube-audio-watchdog.timer' "$ROOT/bin/install.sh"

# The external monitor is independent but intentionally lower-frequency. It
# samples master/video pacing and consumes the fresh local YouTube watchdog
# result instead of launching another expensive audio decode.
grep -Fq "cron: '*/15 * * * *'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
grep -Fq "'sudo /usr/local/bin/fgbears-stream-status --sample-seconds 10'" "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
grep -Fq 'status_file=/srv/fgbears-live/health/youtube-audio/status.env' "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
grep -Fq 'YOUTUBE_WATCHDOG_STATUS_STALE' "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"
if grep -Fq 'fgbears-audio-health --capture-seconds' "$REPO_ROOT/.github/workflows/fgbears-live-monitor.yml"; then
  echo 'External monitor must consume watchdog status rather than duplicate deep audio capture.' >&2
  exit 1
fi

echo 'Separated master, YouTube owner-aware, and external monitoring contracts passed.'

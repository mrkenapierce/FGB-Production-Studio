# FGB legacy workflow quarantine — October 26, 2026

## Scope
Moved **10 Oracle-era FGB streaming workflows** out of the executable GitHub Actions directory and into `.github/quarantine/oracle-legacy-2026-10-26/` with their original Git blobs preserved. These files address legacy `fgbears-live.service` and Oracle-hosted relay/topology, NOT the active `fgb-transport-youtube-1` on OVH. No service, Docker container, player, stream key, CNT job, or database was changed by this quarantine.

Moved files:
- `fgbears-live-monitor.yml`
- `quarantine-legacy-fgbears-runtime.yml`
- `fgbears-encoder-reconnect.yml`
- `fgbears-live-restart-diagnose.yml`
- `fgbears-stream-health-audit.yml`
- `diagnose-youtube-preparing.yml`
- `fgbears-live-deploy.yml`
- `fgbears-live-runtime-tune.yml`
- `deploy-youtube-flv-config-fix.yml`
- `activate-fgb-facebook-live-api.yml`

## Active protections retained
- `.github/workflows/reload-fgb-browser-source.yml` — FGB-only manual CDP refresh, successfully rerun 2026-10-26.
- `.github/workflows/install-fgb-renderer-watchdog.yml` and `ops/transport-ovh/fgb-browser-watchdog.py` — on-host ~30-second DOM renderer watchdog with bounded FGB-only recovery.
- `.github/workflows/deploy-ovh-transport-production.yml` — retained as manual/path-triggered deployment but redundant 5-minute cron removed after permanent handoff.
- `.github/workflows/audit-live-trivia-drift.yml`, `audit-public-trivia-phase-alignment.yml`, CNT capture health, OVH deployment/recovery, and archive workflows remain accessible.
- Windows build workflow retained, but ordinary infrastructure-only GitHub pushes no longer rebuild the desktop EXE.

## Why and how to restore
This is a reversible source-code quarantine; no workflow is deleted from Git history. Restore one by copying its unchanged archived blob to `.github/workflows/<name>` and deleting the archived copy in a reviewed commit. Confirm it points to a valid current host/service before running it.

## Host-process cleanup boundary
This operation removes **GitHub Actions activation paths**, not running OVH/Oracle processes. No systemd unit or Docker container should be stopped until a fresh host inventory proves its identity, destinations, dependencies, and inactivity. CNT's capture, audio, stream key, and video output are explicitly protected.

## Review and unresolved items
- Live archive OAuth diagnostics remain available. The older `check-ovh-archive.yml` should be fixed, not blindly quarantined, because archiving is a current function.
- Root cause of Chromium SIGTRAP remains under investigation; FGB's new renderer watchdog mitigates recurrence, not the underlying crash.

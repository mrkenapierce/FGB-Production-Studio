# FGB Chromium renderer SIGTRAP response — production runbook
**Date:** 2026-10-26 (America/Chicago)
**Boundary:** Live FGB YouTube only. Never touch CNT capture or audio, and do not restart FFmpeg, YouTube ingest, or Docker to remedy only an "Aw, Snap!" browser page.

## Incident and validated recovery
- Viewer screenshot shows Chromium's **Aw, Snap! / SIGTRAP** *inside the transmitted video*, while YouTube live chat still renders; YouTube's player is not the source of the error text.
- GitHub Actions **Reload FGB Browser Source** was rerun on 2026-10-26 15:28 UTC. OVH confirmed `BROWSER_RELOAD_SENT=true`, `LIVE_STATE=live`, correct FGB source/title, FGB container unchanged, zero new restarts. This validates source recovery but not independent YouTube viewer confirmation.
- Capture page: `https://epiccontentcreatorgrants.org/fgb-broadcast?target=youtube`; the CNT page is separate and must remain `/channels/cruisenewstrivia/broadcast`.

## ONE production recovery timer
The canonical `fgb-browser-guard.timer` checks every 20 seconds. The associated `fgb-renderer-probe.py` evaluates the *rendered DOM over Chromium DevTools*, detecting SIGTRAP failures that a PID or open DevTools port misses. After 3 failed checks, it requests an FGB-only replacement tab. At least 180 seconds between recovery attempts, capped at 3 per hour. It checks FGB encoder/container continuity. A fresh Chromium process is a last-resort fallback for an unresponsive target. The companion GitHub deployment is `.github/workflows/deploy-fgb-renderer-guard.yml`.

The separately built `fgb-browser-watchdog.timer` was **disabled on OVH** after identifying this duplicate. Its installer and Python source were moved to `.github/quarantine/duplicate-renderer-watchdog-2026-10-26/` so changes cannot accidentally re-enable it. Do not run two FGB page-recovery timers.

Operator status, no mutation:
```bash
systemctl is-active fgb-browser-guard.timer
systemctl is-enabled fgb-browser-guard.timer
systemctl is-enabled fgb-browser-watchdog.timer # expected disabled
journalctl -u fgb-browser-guard.service --since '30 minutes ago' --no-pager
sudo docker ps --filter name=fgb-transport-youtube-1
```
For one-time manual page recovery, use `.github/workflows/reload-fgb-browser-source.yml`. Do **not** use legacy Oracle or v2 recovery scripts.

## Disk pressure: unresolved infrastructure capacity risk
On 2026-10-26 15:46 UTC, OVH `/dev/sda1` (72 GB) was 100% full (approximately 489 MB available). The FGB archive directory `/srv/fgb-archive` consumed approximately 61 GB. A low-disk condition can destabilize Chromium; this is a strong contributing risk, **not confirmed forensic proof of the SIGTRAP cause**.

At 15:49 UTC, safe pruning of Docker build cache older than 7 days reclaimed **2.826 GB**; filesystem then had about 2.3 GB free (~97% used). No live images, encoder, FGB recordings, or CNT resources were removed.

Archive audit at 15:49 UTC:
- `hourly/`: 34 TS files, 34,158,876,968 bytes
- `final/`: 22 MP4 files, 30,579,530,882 bytes
- `state/`: 488 metadata receipts (477 confirmed, 11 ignored, 0 unconfirmed, 455 media_removed).
- Local TS and MP4 duplicates are retained temporarily even when YouTube publication is confirmed, under the existing **24-hour retention**.
- The archive recorder's free-space preflight requires 8 GB to start; a recorder already running may continue until the disk is full. Current free space remains below this preflight threshold.

**Do not indiscriminately delete archive files.** The user has separately requested archive publishing and sometimes removal of public episodes. Video confirmation should not automatically be interpreted as confirmation that the only local recording is disposable. The repo now has a hardened `cleanup_confirmed` guard which restricts deletion to confirmed YouTube IDs and archive hourly/final directories, but **24-hour retention remains the active default**. A six-hour option was evaluated but **not deployed** pending explicit retention/preservation policy. Do not manually lower retention or rebuild the archive uploader without verifying the user's archive-preservation requirement and the intended impact on recovery/backup copies.

Sustainable remedies:
1. Put recordings on a separate sufficiently sized filesystem/object storage, or expand OVH storage. Allow at least a full day's TS+MP4 archive demand plus free reserve and growth headroom.
2. Decide whether `hourly` TS and `final` MP4 both need local retention after YouTube verification, and which should be offloaded.
3. Verify YouTube OAuth/playlist confirmation, archive publishing backlog, and a minimum 8 GB free-space alert. The current archive health workflow is `.github/workflows/check-ovh-archive.yml`. It correctly fails when storage is below this threshold.
4. Only after documented safe archiving should an automatic confirmed-media expiration policy be activated.

## Workflow/process quarantine
Ten Oracle-era workflows were archived into `.github/quarantine/oracle-legacy-2026-10-26/` (merged PR #100), with all original blobs preserved. The unused five-minute permanent-OVH-deploy cron and infrastructure-triggered Windows rebuilds were removed/restricted. No legacy live containers were found: host listed only FGB encoder, FGB archive uploader, CNT capture. CNT feed relay and CNT trivia watchdog remain current; don't remove them. The duplicate FGB 30-second watchdog was quarantined via PR #102.

## Outstanding verification gates
- Direct YouTube viewer playback after reload; no authenticated YouTube Studio ingest proof was available.
- Durable disk free-space remediation (still ~97% full).
- Investigate Chromium SIGTRAP renderer logs/coredumps, memory and page script spikes after restoring free capacity, and verify that the 20-second guard auto-recovers from a controlled synthetic failure *without touching CNT*.
- Confirm archive OAuth and final publishing status; do not confuse a healthy live encoder with a healthy hourly archive.

**Change control:** Preserve CNT's distinct media, branding, audio, and output; preserve FGB's 10-minute trivia cadence, scoring, rewards, and clock. No database mutations.

# Quarantined historical FGB streaming workflows (2026-10-26)

These 12 workflows have been moved **unchanged**, preserving their exact Git blob objects and history, from the active `.github/workflows/` directory. They are intentionally not discoverable by GitHub Actions and cannot run automatically or through manual workflow dispatch while quarantined.

## Reason
Historical Episode 01/01-31 activation and single-episode cutover; dated September 3 Oracle/Rumble production experiments; an OCI credential probe; and a YouTube-player probe hardcoded to an older video ID. These do not correspond to the current OVH Chromium/FFmpeg capture and CNT channel. Several old jobs contain commands that would restart or reconfigure legacy streaming units if accidentally invoked.

## Exact files
- `activate-first-13-verified.yml` (original Git blob `c97992216919b2321ba916ae11fe1114043eb2b6`)
- `activate-fgb-episodes-14-31.yml` (original Git blob `0bd538204c45a49b0d5afb5caf2f957c9b6f32f6`)
- `cutover-episode01-final.yml` (original Git blob `adb2fa3dfccd6f42ba00452832879bfc04db6b4b`)
- `cutover-episode01-validated-only.yml` (original Git blob `9e25c3db140797d786b10c2f8c64da7a8debd6c7`)
- `cutover-episode01-validated-only-v2.yml` (original Git blob `57761fb46c87c74503fc8b423c8d53c9af3e2803`)
- `deploy-crawl-rgba-clock-fix-20260903.yml` (original Git blob `e04c62fbbc08e7d93bc8d75a729973f38a85f082`)
- `repair-rumble-framesync-20260903.yml` (original Git blob `d35dd3277f17cf8fc06f44695621d2249f2c64ec`)
- `promote-rumble-25fps-stability-20260903.yml` (original Git blob `45e1f78358e6d242db75bc130d1271627eab5505`)
- `probe-looped-ad-frame-20260903.yml` (original Git blob `a8cdedc4b4c7240100f4a211c7cd0e874469d821`)
- `probe-oci-instance-principal-v2.yml` (original Git blob `4c6e88e71ca51ee490bbbd1745d9f435e0372991`)
- `diagnose-v3-cutover-failure-20260903.yml` (original Git blob `9b04d2c8490b9baa4d65bcafb60012758490fc32`)
- `probe-youtube-player-config.yml` (original Git blob `f4ecd0708babfed66a0b4dd392f72fc81e04ced0`)

## Recovery
Move a file back to `.github/workflows/<original-name>` on a dedicated review branch after verifying the applicable infrastructure. The original blob SHA must remain identical. Do not execute these scripts against current FGB/CNT without an updated topology audit.

## Preserved active paths
The OVH FGB capture/encoder, archive uploader, CNT capture/browser/audio, current shared trivia feeds, recovery workflows `reload-fgb-browser-source.yml` and `refresh-ovh-browser-source.yml`, FGB/CNT drift audits, and the new FGB renderer watchdog are **not** quarantined or stopped.

## Operational safety
No running Docker containers, systemd units, stream keys, or live data are touched by this Git-only workflow quarantine. A separate read-only server inventory is required before taking any runtime service offline.

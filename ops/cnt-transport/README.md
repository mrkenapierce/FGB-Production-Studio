# Cruise News & Trivia — independent 24/7 encoder deployment

Prepared on branch `cnt-ingest-preflight-20261025`. FGB remains untouched.

## Existing evidence (2026-10-25)
- CNT-specific `CNT_YOUTUBE_STREAM_KEY` is available to GitHub Actions.
- A 120-second FFmpeg test to the CNT YouTube ingest completed with success. This does not establish an ongoing live event.
- OVH VPS `vps-a13eee97.vps.ovh.us` reports **running** through the OVH API.
- The historic OVH address `40.160.144.185` accepts TCP on port 22 but **closes the connection before sending an SSH banner**. No remote login is possible from GitHub Actions.
- Published CNT route returned HTTP 200; the separate news endpoint was reporting stale with zero items, needing source-refresh investigation.

## Safe repair prerequisite
1. Verify the VPS's current IPv4 address in https://manager.us.ovhcloud.com/ . Correct the target in the CNT-only workflow if it changed.
2. Restore a functioning SSH daemon using OVH's out-of-band console or qualified administrator. Read SSH logs and the listener status; do **not** reboot, rescue-boot, reinstall, stop or restart the existing FGB service just to bring CNT online.
3. Re-run the CNT-only read-only preflight and verify that the host responds with an SSH banner, accepts the existing protected deployment key and has CPU/RAM headroom.
4. Review the isolated workflow `.github/workflows/cnt-ovh-deploy-only.yml`. It stages only `/opt/cnt-transport`, injects **only** the CNT stream key from GitHub Actions and starts `epic-cnt-capture` under its own Compose project. It never reads FGB stream keys or restarts the FGB Compose project.
5. After the workflow reports CNT video encoder progress, verify in **Cruise News & Trivia** YouTube Studio that the channel receives video and audio, and keep the initial event unlisted until the preview is correct.

## Deployment activation
The deployment workflow does not automatically run when committed. On this branch, creating `ops/cnt-transport/START.txt` triggers it after the prerequisites pass. No trigger file exists yet. Avoid multiple concurrent attempts.

## Why this isn't live yet
GitHub's earlier short FFmpeg test succeeded but has ended. A **permanent** 24/7 source must run on an always-on host with capacity, valid credentials and a working SSH deployment path. The current OVH connection fails at protocol negotiation, before authentication.

# CNT SIGTRAP production deployment — November 4, 2026

## Status
**Deployed:** 2026-11-05T01:12:47Z (November 4, 7:12:47 PM America/Chicago) on OVH VPS `vps-a13eee97.vps.ovh.us`.

**Not yet closed as permanently eliminated:** renderer crash root cause not established; production crash-injection/recovery under SIGTRAP and complete viewer-side YouTube audio/video verification outstanding; 48-hour stability observation in progress.

## Production changes
- Removed FGB's continuous YouTube encoder before the CNT cutover, preserving FGB's archive uploader and individual video channel.
- CNT container `epic-cnt-capture` in `epic-cnt-transport` Compose project was replaced via the **existing** `/opt/cnt-transport/docker-compose.phase2.yml` plus scoped `docker-compose.cnt-hardening-20261104.yml` override.
- New image `epic-cnt-phase2:hardened-20261104`, image ID `sha256:0fc522700f6589be7cf58b2b48323e793938f5c5c77e765b8c43d9480bcfc440`.
- The replacement was built **FROM the exact production capture image**, keeping its Chromium, FFmpeg and archive code intact. Installed SIGTRAP page/renderer watchdog, isolated browser process-group recovery, safe diagnostics collector, and preserved original encoder/archive tap.
- Preserved `/srv/cnt-archive:/cnt-archive` bind, network `epic-cnt-transport_cnt-only`, unchanged `epic-cnt-archive-worker`, unchanged `fgb-transport-archive_uploader-1`, FGB livestream still stopped.
- Applied CNT limits: CPU 2 cores, memory 3072 MiB, shared memory 1024 MiB, pids 256. Added named persistent state volume `epic-cnt-capture-state` (do not prune).
- Fenced the rollout: original CNT sender stopped and zero running senders confirmed before new sender started. New container had one sender, healthy browser watchdog and fresh FFmpeg progress after startup.

## Safe rollback
Original running capture image ID before cutover:
`sha256:c89e2c4e300f20d1b18ab65997dbb3eb69a3a8c4ec4bcdb6807cb10209d4a8b1`.
Pinned on OVH to image tag **`epic-cnt-phase2:rollback-20261104`**.

**Important:** do NOT assume the mutable `epic-cnt-phase2:staged` tag is identical to the original capture; the separate archive worker used a different image ID. For rollback, explicitly override CNT's image to `epic-cnt-phase2:rollback-20261104`, stop only CNT, verify one sender, recreate CNT only with `--no-deps --no-build`, and verify its image ID is exactly the pinned original. Preserve the archive worker and FGB uploader, and never run `compose down`, prune, or delete recordings.

## Evidence and acceptance
- Offline hardened image build and host compatibility: https://github.com/mrkenapierce/FGB-Production-Studio/actions/runs/41946193984
- OVH measured preflight and staging: https://github.com/mrkenapierce/FGB-Production-Studio/actions/runs/41946406308
- **Successful CNT production cutover:** https://github.com/mrkenapierce/FGB-Production-Studio/actions/runs/41946819615
- First independent GitHub 48h monitor check: https://github.com/mrkenapierce/FGB-Production-Studio/actions/runs/41947219831

At post-deploy verification, Docker health and watchdog status were **healthy**, watchdog reported `action=ok`, `reason=ok`, zero consecutive failures, zero restarts, no origin outage, no alert. Later GitHub monitor confirmed all 12 status checks passed, fresh encoder progress, no OOM kills, 1 CNT sender, archive worker/uploader operational, FGB stream off.

GitHub Actions `.github/workflows/cnt-hardening-48h-soak-20261104.yml` checks the host every 15 minutes (subject to GitHub scheduling delays) during **2026-11-05T01:12:47Z to 2026-11-07T01:12:47Z**. Issues labeled `cnt-sigtrap-soak` are generated on detected problems. This is external monitoring from GitHub, not a proof of YouTube viewer-side ingest.

## Unresolved / follow-up
1. Confirm directly in YouTube Studio or authenticated channel analytics that CNT is visibly live, with moving picture and audible audio; container/FFmpeg health is not sufficient.
2. Verify real renderer crash recovery in an isolated offline test, then decide whether a controlled production test is warranted.
3. Accumulate the 48h production stability evidence, including any SIGTRAP patterns, restarts, cgroup pressure and archive publication continuity.
4. Preserve separate FGB on-demand publishing, and maintain startup controls so the discontinued FGB stream does not restart.
5. Root cause remains unproven; call the implementation **deployed hardening and recovery**, not a proven elimination of SIGTRAP.

## Operational ideas / end-of-day log
- Prefer preserving the deployed production image's binary tools and archive topology over generic template replacement.
- A measured in-place replacement CPU gate avoids double-counting the existing sender, while maintaining safety reserve.
- Maintain a single CNT sender, a pinned rollback image, source-independent monitoring, and evidence-based escalation.

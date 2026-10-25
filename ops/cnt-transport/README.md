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


## Non-disruptive SSH recovery from OVH KVM (not executed)
OVH's VPS hostname resolves to `40.160.144.185` (verified 2026-10-25). The VPS is running but closes remote TCP/22 before its SSH protocol banner. No standard SSH client or GitHub Actions can log in until the VPS OS/network issue is repaired.

Use the OVHcloud Manager > Bare Metal Cloud > Virtual private servers > `vps-a13eee97.vps.ovh.us` > `...` beside VPS Name > **KVM**. This is out-of-band console access and does not itself reboot the VPS. Log in with an OS account in the console (never disclose passwords or keys in a public issue/chat).

Read-only diagnostic commands after OS login:
```bash
printf 'SERVER: '; hostname
sudo systemctl --no-pager --full status ssh || true
sudo /usr/sbin/sshd -t && echo SSH_CONFIG=VALID || echo SSH_CONFIG=INVALID
sudo ss -ltnp | grep ':22 ' || echo SSH_LISTENER=MISSING
sudo journalctl -u ssh --no-pager -n 65
sudo docker ps --format 'FGB_CHECK={{.Names}} {{.Status}}'
```
If SSH is inactive AND `sshd -t` succeeds, consider `sudo systemctl start ssh` (SSH service only). Do not reboot/reinstall the VPS or restart any FGB Docker service. If SSH is running but external connections close immediately, inspect SSH `MaxStartups`, `fail2ban` and OS firewalls, and confirm a valid listening interface and network access; use targeted repair rather than disabling security globally.

After SSH remote connections authenticate and host capacity passes, the already prepared GitHub workflow `.github/workflows/cnt-ovh-deploy-only.yml` can deploy `epic-cnt-capture` independently. Do not create `START.txt` before these gates pass.

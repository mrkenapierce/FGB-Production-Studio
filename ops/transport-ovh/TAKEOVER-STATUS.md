# OVH Transport Takeover Status

GitHub Actions is the deployment controller for the FGB OVH transport migration.

## Target

- Host: `40.160.144.185`
- Provider: OVHcloud VPS
- Purpose: staging transport for Lovable `/fgb-broadcast` -> FFmpeg -> YouTube
- Production cutover: **not authorized by this automation**; explicit final go-live approval remains required.

## GitHub-managed pieces

1. `prepare-ovh-vps-key.yml`
   - Derives the public half of the existing protected deployment key (`ORACLE_SSH_KEY`) without exposing the private key.
   - Public key: `ops/transport-ovh/ovh-deploy.pub`.

2. `deploy-ovh-transport-staging.yml`
   - Retries the OVH host automatically every 30 minutes.
   - Discovers the supported SSH login account (`ubuntu`, `debian`, or `root`).
   - Runs `bootstrap-ovh.sh` as root/sudo after SSH becomes available.
   - Verifies Docker + SSH are active.
   - Verifies the livestream service is disabled and stopped before host-only secrets are supplied.
   - Writes sanitized status to `.github/deployment-status/ovh-transport-staging.json` after success.

3. `bootstrap-ovh.sh`
   - Installs/updates SSH, Docker, Compose, Git, UFW and supporting packages.
   - Builds the transport image.
   - Restricts inbound firewall access to SSH.
   - Installs the `fgb-transport.service` systemd unit.
   - Creates `NEEDS_SECRETS` and prevents the transport from starting until secure host configuration is complete.

4. `inspect-oracle-fgb-transport.yml`
   - Collects only filenames/unit names/path metadata from the existing Oracle transport.
   - Never reads or commits secret values.

## Current external blocker

The OVH host is reachable at the network layer, but SSH on TCP/22 is not accepting connections. GitHub Actions therefore cannot yet enter the server to run the bootstrap. The GitHub deployment workflow will continue retrying automatically.

No production YouTube stream key has been copied to OVH, no OVH transport has been started, Oracle has not been altered, and no production cutover has occurred.

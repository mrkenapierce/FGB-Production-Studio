# OVH Transport Takeover Status

GitHub Actions is now the direct deployment controller for the FGB OVH transport migration. No browser automation is part of the deployment path.

## Target

- Host: `40.160.144.185`
- Provider: OVHcloud VPS
- Purpose: staging transport for Lovable `/fgb-broadcast` -> FFmpeg -> YouTube
- Production cutover: **not authorized by this automation**; explicit final go-live approval remains required.

## Direct deployment architecture

`GitHub Actions -> SSH/TCP 22 -> OVH VPS -> Docker/Chromium/FFmpeg -> YouTube`

The GitHub runner directly tests and uses SSH. Browser automation, TinyFish, and browser-extension credits are not required for this deployment workflow.

## Verified state

- OVH TCP/22 is open from GitHub-hosted runners.
- The server returns an SSH host key/banner.
- The current legacy protected `ORACLE_SSH_KEY` does **not** authenticate as `ubuntu`, `debian`, or `root`.
- The transport Docker image builds successfully in GitHub Actions.
- An isolated GitHub-hosted dry run successfully rendered the live Lovable broadcast page through Chromium + FFmpeg with local-only FLV output; no YouTube stream was started.

## GitHub-managed pieces

1. `deploy-ovh-transport-staging.yml`
   - Uses direct GitHub-to-OVH SSH only.
   - Prefers a dedicated protected `OVH_SSH_KEY`; falls back to the legacy `ORACLE_SSH_KEY` only if needed.
   - Performs a direct TCP/22 and SSH-banner preflight.
   - Discovers `ubuntu`, `debian`, or `root` after authentication.
   - Builds the transport image before remote deployment.
   - Runs `bootstrap-ovh.sh` remotely after authentication succeeds.
   - Verifies Docker + SSH are active and the livestream service is stopped before host-only secrets are supplied.
   - Writes sanitized status after success.

2. `bootstrap-ovh.sh`
   - Installs/updates SSH, Docker, Compose, Git, UFW and supporting packages.
   - Builds the transport image.
   - Restricts inbound firewall access to SSH.
   - Installs the `fgb-transport.service` systemd unit.
   - Creates `NEEDS_SECRETS` and prevents the transport from starting until secure host configuration is complete.

3. `validate-github-hosted-transport.yml`
   - Builds the same transport image on a GitHub-hosted runner.
   - Loads the real Lovable broadcast source.
   - Encodes to a local FLV only for validation.
   - Never sends a production stream.

4. `diagnose-ovh-direct.yml` and `diagnose-ovh-auth.yml`
   - Verify direct network and authentication state without exposing credentials.

## Current blocker

The deployment path itself no longer depends on TinyFish. The only remaining OVH blocker is authorization: a private key available to GitHub must match a public key authorized on the VPS. Once that key relationship exists, the GitHub workflow can bootstrap and administer the VPS directly without browser interaction.

No production YouTube stream key has been copied to OVH, no OVH transport has been started, Oracle has not been altered, and no production cutover has occurred.

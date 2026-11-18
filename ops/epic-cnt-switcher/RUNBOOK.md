# CNT → EPIC YouTube destination switch — activation runbook (INACTIVE)

Built (inactive): admin request fn + gates, epic_destination_* tables (admin-read RLS, service-only writes,
one-active-op unique lock, durable nonces, append-only audit), signed pull endpoint
`POST /api/public/channels/cruisenewstrivia/destination-agent` (503 until secret set; v2 HMAC with
role-separated keys, 60 s skew, DB nonce claim, 4 KB cap, rate cap), state machine
pending→claimed→acked→switched | rolling_back→rolled_back | failed (rollback_unverified ⇒ destination unknown),
full agent `ops/transport/cnt-destination-agent.py`, opt-in `run-cnt.sh` alias support (started by run-cnt.sh inside the CNT container; no host systemd unit).
Nothing is deployed, published, or switched.

## Find the host service (no secrets needed)
On the CNT host: `systemctl list-units --type=service | grep -i cnt` ; `docker ps --format '{{.Names}} {{.Image}}' | grep -i cnt` ;
`pgrep -af run-cnt.sh` ; `readlink -f /proc/$(pgrep -f run-cnt.sh | head -1)/cwd`. Report names/paths only.
The agent MUST run in the same namespace as run-cnt.sh (same container if Dockerized) so it sees
`/cnt-state/destination` and `/tmp/cnt-ffmpeg.progress`.

## Operator steps (in order, each needs approval for production)
1. Deploy updated `run-cnt.sh` + agent to the host checkout. Leave `CNT_DESTINATION_SWITCHING` unset → behaviour identical to today.
2. YouTube Studio as @EPICContentCreatorGrants → Go live → Stream → reusable key. Put `EPIC_YOUTUBE_INGEST_URL=rtmps://a.rtmps.youtube.com/live2` and `EPIC_YOUTUBE_STREAM_KEY` in the host's private env only. CNT key untouched.
3. Create one strong random value; save as `CNT_DESTINATION_AGENT_SECRET` in Project Settings → Secrets AND the host agent env file (mode 600).
4. Admin → Channels → EPIC Content Creator Grants → Connect YouTube with the brand account (grant must include YouTube read access). Then Admin → YouTube Broadcast Destination → Verify EPIC channel.
5. Publish (separate approval). Set `CNT_DESTINATION_SWITCHING=on` + `CNT_DESTINATION_AGENT_URL` on host, restart CNT runner in a quiet window (separate approval), start agent.
6. Confirm all four gates read Verified; then a single supervised switch.

## Update (Nov 18 2026)
- EPIC "Connect YouTube" now auto-provisions EPIC's own sealed copy of CNT's Google OAuth app client (never CNT tokens). No manual client entry.
- The callback refuses to store an EPIC refresh token unless authenticated channels.list proves @EPICContentCreatorGrants.
- Ingest health is bound to this encoder's key: the agent reports SHA-256 of the applied stream key (`keyFingerprint`); only the liveStream whose `cdn.ingestionInfo.streamName` hashes to it counts. No fingerprint/match → unknown → switch stays disabled.
- Repo-documented CNT host layout (unconfirmed on the real host): docker compose profile `cnt`, container `epic-cnt-capture`, env file `.env.cnt`, state volume `epic-cnt-capture-state`; agent example unit `/opt/epic-transport/ops/transport`.

## Production topology (verified Nov 18 2026)
- Host 40.160.144.185, Compose project `epic-cnt-transport`, service `cnt`, container `epic-cnt-capture`, directory `/opt/cnt-transport`, env `/opt/cnt-transport/.env.cnt`, base image `epic-cnt-phase2:hardened-20261104`.
- The agent is NOT a host systemd service: on the host it cannot see the container's `/tmp/cnt-ffmpeg.progress` or ffmpeg PID. `Dockerfile.cnt` bundles `cnt-destination-agent.py` + `cnt-destination-gate.sh`; `run-cnt.sh` runs the agent as its own child in the same container.
- Startup order: Chromium → `cnt_destination_gate` → first ffmpeg → agent. If `CNT_DESTINATION_SWITCHING=on` lacks a valid `CNT_DESTINATION_AGENT_URL` or a ≥32-char `CNT_DESTINATION_AGENT_SECRET`, switching is forced off, a non-secret warning is logged, any stale alias file is ignored and ffmpeg uses the original CNT ingest. When off, no agent is spawned.
- Shutdown stops agent → ffmpeg → Chromium → display/audio. The agent is pull-only (no inbound port) and is restarted by the main loop if it exits.
- Still missing (operator): `EPIC_YOUTUBE_STREAM_KEY`/`EPIC_YOUTUBE_INGEST_URL` in `.env.cnt` (from EPIC YouTube Studio — never copy CNT's key), EPIC OAuth connection, `CNT_DESTINATION_AGENT_SECRET` in app secrets + `.env.cnt` (+ GitHub Actions if used). The website endpoint stays 503 until its secret exists.
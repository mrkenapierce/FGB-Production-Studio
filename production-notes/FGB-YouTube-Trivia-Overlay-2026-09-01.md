# FGB YouTube-only trivia overlay — production status

**Local status time:** 2026-09-01 23:52 America/Chicago

## Approved architecture retained

- Production VM remains the master source and must not perform the YouTube mask video re-encode.
- Source-to-compositor transport is copy-only SRT/MPEG-TS using `youtube-compositor-source-relay.sh` (`-c copy`).
- YouTube video composition and encoding are isolated to the dedicated off-host compositor using `youtube-offhost-compositor.sh`.
- The YouTube-only mask covers only the configured live question-and-choice region; the rest of the frame remains transparent.
- Mask activation trusts authoritative `trivia.youtubeMaskActive === true` only during `phase === "question"`.
- Missing, malformed, stale, or unreachable routing state fails transparent.
- Rumble remains on the unmasked master feed.
- Free Oracle capacity must be checked first. Do not provision a paid resource without separate authorization.

## Verification completed

- Off-host compositor CI tests previously passed syntax, partial-mask geometry/transparency, and source-host isolation checks; the compositor implementation has not changed since that test commit.
- Live routing was observed in both states:
  - revealed phase: `questionActive=false`, `youtubeMaskActive=false`
  - question phase: `questionActive=true`, `stale=false`, `youtubeMaskActive=true`
- Final read-only production health verification at approximately 23:51 Central:
  - `fgbears-live.service`: active
  - `fgbears-youtube-relay.service`: active
  - `fgbears-rumble-relay.service`: active
  - current YouTube relay remains copy-only and has an established RTMPS socket
  - 20-second source audio sample: AAC, 48 kHz, stereo
  - clipping ratio: 0 on both channels
  - audio PTS regressions: 0
  - large audio PTS gaps: 0
  - YouTube relay audio timestamp error lines: 0
  - audio health result: `OVERALL_STATUS=OK`

## Oracle provisioning blocker — still active

A fresh instance-principal check at approximately 23:47 Central confirmed:

- OCI region enumeration succeeds with the production VM instance principal.
- OCI Compute access still returns `NotAuthorizedOrNotFound` for `get_instance`.
- Therefore the current principal cannot safely enumerate/verify free Compute capacity or provision the separate compositor.
- A fresh GitHub credential-presence probe at approximately 23:52 Central confirmed that no OCI/Oracle user API credentials are present in GitHub Actions.

The user's interactive Oracle console sign-in does not change the VM instance principal authorization, and the authenticated console is not exposed as a controllable surface in the current chat session.

## Cutover status

**No YouTube compositor handoff was performed.** The current direct YouTube copy-remux relay remains in production. The master encoder and Rumble relay were not restarted or modified by this work.

The off-host compositor must be provisioned and verified before the authorized brief YouTube-only handoff can occur.

## Security remediation performed

A diagnostic workflow was found to print full relay command lines into GitHub Actions logs. Future runs were changed to redact RTMP/RTMPS/SRT destinations before printing process arguments. Commit: `c85fd279cd28e5e977833484d3040a4da0fe2f35`.

Because an earlier public Actions log contained live ingest destinations, the YouTube and Rumble ingest credentials shown in that historical log should be treated as exposed. They were not reproduced in this note. Remaining remediation is to rotate the affected platform ingest credentials and purge the historical log when platform/GitHub controls are available; this was not done here because Rumble disruption was explicitly prohibited for this task.

## Exact next production step

1. Obtain an authenticated Oracle Compute control path: either interactive Oracle console control or least-privilege OCI provisioning credentials/policy.
2. Enumerate **free-eligible** capacity first; stop before any paid resource.
3. Provision the dedicated off-host compositor only if a free resource is available.
4. Install the existing compositor/mask implementation and connect the copy-only SRT source relay.
5. Verify transparent fail-safe behavior, live question activation, video/audio health, and Rumble continuity.
6. Perform the authorized brief **YouTube-only** handoff.
7. If verification fails, return YouTube to the existing direct copy-remux relay without touching the master encoder or Rumble.

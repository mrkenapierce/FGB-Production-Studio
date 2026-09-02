# FGB YouTube-only trivia overlay — production status

**Original status time:** 2026-09-01 23:52 America/Chicago  
**Current emergency status time:** 2026-09-02 02:20 America/Chicago

## Approved architecture retained

- Production VM remains the master source and must not perform the YouTube mask video re-encode.
- Source-to-compositor transport is copy-only SRT/MPEG-TS using `youtube-compositor-source-relay.sh` (`-c copy`).
- YouTube video composition and encoding are isolated to the dedicated off-host compositor using `youtube-offhost-compositor.sh`.
- The YouTube-only mask covers only the configured live question-and-choice region; the rest of the frame remains transparent.
- Mask activation trusts authoritative `trivia.youtubeMaskActive === true` only during `phase === "question"`.
- Missing, malformed, stale, or unreachable routing state fails transparent.
- Rumble remains on the unmasked master feed.
- Free Oracle capacity must be checked first. Do not provision a paid resource without separate authorization.

The off-host compositor remains the preferred long-term architecture. The emergency packet router described below is an authorized interim production safeguard because the direct YouTube copy-remux path exposed trivia questions.

## Verification completed before emergency switch

- Off-host compositor CI tests previously passed syntax, partial-mask geometry/transparency, and source-host isolation checks; the compositor implementation has not changed since that test commit.
- Live routing was observed in both states:
  - revealed phase: `questionActive=false`, `youtubeMaskActive=false`
  - question phase: `questionActive=true`, `stale=false`, `youtubeMaskActive=true`
- Final read-only production health verification before the emergency work showed:
  - `fgbears-live.service`: active
  - `fgbears-youtube-relay.service`: active
  - `fgbears-rumble-relay.service`: active
  - YouTube direct relay was copy-only and had an established RTMPS socket
  - audio health result: `OVERALL_STATUS=OK`

## Oracle provisioning blocker — historical context

A prior instance-principal check confirmed:

- OCI region enumeration succeeded with the production VM instance principal.
- OCI Compute access returned `NotAuthorizedOrNotFound` for `get_instance`.
- The VM principal therefore could not safely provision the dedicated compositor itself.
- GitHub Actions did not contain OCI/Oracle user API credentials.

The user later proceeded through the Oracle console manually, but the emergency packet-router path below was activated first to stop YouTube question exposure without touching Rumble or restarting the master encoder.

## Emergency YouTube-only production override — ACTIVE

The user explicitly authorized the emergency switch on 2026-09-02 after confirming that trivia questions were still visible on YouTube.

The active emergency path uses the already-tested low-CPU packet router:

- `fgbears-youtube-router.service` is the active/enabled YouTube branch.
- The router receives the existing encoded H.264/AAC MPEG-TS branch, performs packet-level video selection, and does **not** re-encode video.
- During a fresh authoritative question state, defined as `trivia.youtubeMaskActive === true`, `trivia.phase === "question"`, and `trivia.stale === false`, YouTube switches at a keyframe from the live H.264 program to the pre-encoded full-frame Rumble trivia card.
- When the question-safe state clears, YouTube switches back to the live encoded program at a keyframe.
- The YouTube audio repair is preserved: AAC-LC, 128 kbps, 44.1 kHz, stereo, asynchronous resampling.
- Endpoint failures or stale/malformed state fail open to the normal live program.
- `fgbears-youtube-relay.service`, the old direct path that exposed questions, is disabled while emergency mode is active.
- `fgbears-youtube-audio-watchdog.timer` is disabled because it would otherwise restart the old direct relay.
- The normal `fgbears-live-health.service` remains enabled and is redirected through a systemd drop-in to supervise `fgbears-youtube-router.service` instead of the disabled direct relay.
- The router itself is configured `Restart=on-failure` and enabled for boot persistence.

## Emergency cutover verification — PASSED

The guarded cutover completed successfully in GitHub Actions run `33602535496`.

Observed production results:

- YouTube RTMPS transport established 13 seconds after the authorized branch handoff.
- Router PID after cutover: `2195195`.
- No fatal router, GStreamer, or FFmpeg-transport exit events were detected during the post-connect stability window.
- `fgbears-live.service` remained on PID `2112260`; master encoder restart: **no**.
- `fgbears-rumble-relay.service` remained on PID `2191628`; Rumble restart: **no**.
- Video re-encode added by emergency path: **no**.
- YouTube audio repair preserved: **yes**.

A separate next-question verification completed successfully in GitHub Actions run `33602815656`:

- 2026-09-02 02:20:03 America/Chicago: authoritative question-safe state observed.
- 02:20:04: router logged `video route switched: live -> card`.
- YouTube RTMPS remained established while the card was active.
- 02:20:16: authoritative state cleared to `phase=revealed`, `youtubeMaskActive=false`, `stale=false`.
- 02:20:17: router logged `video route switched: card -> live`.
- Verification result: `NEXT_QUESTION_EMERGENCY_SWITCH=PASS`.
- Master encoder restart: **no**.
- Rumble relay restart: **no**.
- Emergency YouTube router remained active after verification.
- Direct YouTube relay remained inactive after verification.

This confirms that the production YouTube branch now substitutes the full-frame Rumble card during the actual protected question interval and returns to the normal live program after the question. It is a full-frame emergency substitution, so the YouTube crawl/news layers are also hidden for the protected question interval. Rumble remains on the unmodified master program.

## Rollback protocol

If the emergency router becomes unhealthy or must be removed:

1. Stop and disable `fgbears-youtube-router.service`.
2. Remove `/etc/systemd/system/fgbears-live-health.service.d/90-youtube-emergency-router.conf` and run `systemctl daemon-reload`.
3. Re-enable and start `fgbears-youtube-relay.service`.
4. Re-enable and start `fgbears-youtube-audio-watchdog.timer`.
5. Verify YouTube RTMPS transport, master health, and Rumble continuity.
6. Do not restart or modify the master encoder or Rumble relay as part of this rollback.

The guarded deployment workflows already implement this YouTube-only rollback automatically on cutover failure.

## Security remediation performed

A diagnostic workflow was found to print full relay command lines into GitHub Actions logs. Future runs were changed to redact RTMP/RTMPS/SRT destinations before printing process arguments. Commit: `c85fd279cd28e5e977833484d3040a4da0fe2f35`.

Because an earlier public Actions log contained live ingest destinations, the YouTube and Rumble ingest credentials shown in that historical log should be treated as exposed. They were not reproduced in this note. Remaining remediation is to rotate the affected platform ingest credentials and purge the historical log when platform/GitHub controls are available; this was not done here because Rumble disruption was explicitly prohibited for this task.

## Long-term production step

The emergency packet router is now the active protective layer. The preferred final architecture remains the dedicated off-host compositor because it can mask only the question/answer region while preserving the rest of the YouTube picture.

Before replacing the emergency router with the off-host compositor:

1. Provision and verify the dedicated compositor without touching the master or Rumble path.
2. Connect the copy-only SRT source relay.
3. Verify transparent fail-safe behavior, partial-mask geometry, live question activation, video/audio health, and Rumble continuity.
4. Perform a guarded YouTube-only handoff with the direct relay retained as rollback.
5. Remove the emergency full-frame router only after the partial-mask compositor passes a live question-cycle verification.

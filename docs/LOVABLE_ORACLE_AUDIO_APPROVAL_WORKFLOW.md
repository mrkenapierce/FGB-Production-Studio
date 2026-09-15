# Lovable → Oracle Audio Approval and Deployment Workflow

Status: proposed / non-production

## Objective

Move an approved FGB livestream audio asset from Lovable to Oracle, modify it into the canonical production format, validate it without disturbing the live media clock, and deploy it automatically within a few minutes.

Normal target: 2–4 minutes from Lovable approval to verified on-air audio.

## Production principles

1. Lovable is the approval/control plane.
2. Oracle is the execution plane.
3. Approval authorizes processing; it does not permit an unvalidated source file to replace live audio.
4. All download, probing, conversion, loudness adjustment, hashing, and full-file validation happen before the live master is touched.
5. No HTTP request or conversion occurs inside the FFmpeg live-media loop.
6. The live master must retain resource priority over audio preparation.
7. Any failed validation or pacing check leaves or restores the last known-good audio automatically.
8. YouTube remains a direct FFmpeg copy/remux of the shared master; destination relays must not re-clock or re-encode the program.

## State machine

Lovable exposes an immutable approved audio revision. Oracle tracks execution state for that revision.

Lovable/control states:

- `uploaded` — asset exists but is not authorized for production.
- `approved` — operator has approved this exact asset/revision for Oracle processing.

Oracle execution states:

- `detected`
- `downloading`
- `processing`
- `validating`
- `ready`
- `deploying`
- `verifying`
- `live`
- `failed`
- `rolled_back`

A new upload alone never deploys. Only a new `approved` revision is actionable.

## Phase 1 — Approval in Lovable

The Lovable audio panel should use an explicit action such as **Approve for Livestream**.

On approval Lovable should publish, in `presentation.audio` or a compatible deployment-intent object:

- `revision` — monotonically increasing integer
- `approvalState: "approved"`
- `approvedAt`
- `activeTrackId`
- `activeTrackName`
- `assetUrl`
- `sourceSha256`
- `loop: true`
- `volumeGainDb`

The source SHA-256 is required so Oracle can prove it processed the exact asset that was approved.

## Phase 2 — Oracle intake

Oracle polls Lovable every 15 seconds outside the live FFmpeg loop.

When `revision > appliedRevision` and `approvalState == "approved"`:

1. Acquire a non-blocking deployment lock.
2. Create `/srv/fgbears-live/audio/incoming/rev-<revision>/`.
3. Download the approved source to a temporary file.
4. Enforce the existing source-size ceiling.
5. Compute SHA-256 and compare it with Lovable's approved SHA-256.
6. Probe source codec, sample rate, channels, bitrate, duration, and packet timestamps.
7. Record state `downloaded` / `processing`.

If the hash or source probe fails, mark the revision failed and keep current live audio unchanged.

## Phase 3 — Resource-capped Oracle preparation

Preparation is isolated from the live master in its own oneshot service/cgroup.

Recommended service controls:

- `Nice=19`
- `IOSchedulingClass=idle`
- `CPUWeight=1`
- `CPUQuota=25%`
- `MemoryMax=384M`

The live `fgbears-live.service` receives no new limit and therefore retains scheduling priority.

Canonical output profile:

- container: M4A
- codec: AAC
- bitrate: 256 kbps
- sample rate: 48,000 Hz
- channels: 2
- timestamps regenerated from zero
- static gain only
- target integrated loudness: approximately -16 LUFS
- maximum true peak: -1.5 dBTP
- no compressor, limiter, EQ, denoise, de-esser, or dynamic loudness processing

If the approved source is already canonical and no gain is required, Oracle may perform a safe stream copy. Otherwise Oracle transcodes once into the canonical profile.

Use the existing `prepare-audio-track-v3.py` profile logic as the basis for production preparation rather than the looser conversion currently embedded in `lovable-audio-sync.py`.

## Phase 4 — Pre-deployment validation

The candidate cannot touch the live path until all gates pass.

Required gates:

1. Full-file decode completes with zero FFmpeg errors.
2. Output codec is AAC.
3. Output sample rate is exactly 48,000 Hz.
4. Output has exactly 2 channels.
5. Output duration differs from source duration by no more than 0.25% or 0.5 seconds, whichever is greater.
6. Packet PTS/DTS values are monotonic.
7. Output integrated loudness is within the approved production tolerance around -16 LUFS.
8. Output true peak is no higher than -1.5 dBTP.
9. Output SHA-256 and measured metadata are recorded in a candidate manifest.
10. Live master remains active and its progress clock advances during the entire preparation phase.

Passing these gates changes the revision to `ready`.

## Phase 5 — Atomic deployment

Only the already-prepared canonical candidate is used during cutover. No conversion happens during deployment.

1. Snapshot currently active destination services.
2. Back up `/srv/fgbears-live/audio/fgb-music-loop.m4a` into revisioned quarantine storage.
3. Copy candidate to a sibling staging path.
4. Set owner/group and mode.
5. Atomically rename the candidate over `fgb-music-loop.m4a`.
6. Restart only the shared master because that process must reopen the audio file.
7. Do not independently modify destination codec/timestamp behavior.

Expected cutover window: seconds, because all expensive work already completed.

## Phase 6 — On-air pacing verification

A simple "progress increased" test is insufficient. The new deployment must prove that media time advances at real-time speed.

After restart:

1. Verify `fgbears-live.service` is active.
2. Verify the master FFmpeg process has the canonical audio file open.
3. Sample FFmpeg `out_time` at T0.
4. Wait 12–15 seconds wall-clock.
5. Sample `out_time` again.
6. Compute `media_delta / wall_delta`.
7. Require a pacing ratio between 0.98 and 1.02.
8. Verify every destination service that was active before deployment remains active.
9. Verify the YouTube branch remains a direct FFmpeg `-c copy` relay with established RTMPS connectivity.

If any gate fails, rollback automatically.

## Phase 7 — Automatic rollback

Rollback is deterministic:

1. Restore the immediately previous canonical audio backup atomically.
2. Restart the shared master once.
3. Verify real-time pacing again.
4. Mark the attempted revision `rolled_back` with the failing gate and diagnostic details.
5. Do not retry that same revision automatically.

A new Lovable approval/revision is required before another deployment attempt.

## Status returned to Lovable

Recommended admin display:

- Approved
- Oracle detected
- Downloaded
- Processing
- Validating
- Ready
- Deploying
- Live
- Failed / Rolled back

For full round-trip status, add a small authenticated Lovable endpoint accepting an Oracle deployment-status POST signed with a shared HMAC secret. The public routing endpoint remains read-only and authoritative for desired state.

Minimum status payload:

- `revision`
- `trackId`
- `state`
- `message`
- `sourceSha256`
- `canonicalSha256`
- `startedAt`
- `completedAt`
- `pacingRatio`
- `rollbackRevision`

## Timing budget

Typical target after Lovable approval:

| Stage | Target |
| --- | ---: |
| Poll/detect | 0–15 sec |
| Download + hash | 5–30 sec |
| Canonical preparation | 20–90 sec |
| Full validation | 10–30 sec |
| Atomic cutover/restart | 10–20 sec |
| Real-time pacing verification | 15–25 sec |
| **Typical total** | **~1–3 min** |
| **Operational SLA** | **≤4 min normally** |

Large or malformed files may exceed the normal target, but they must never bypass validation to meet the clock.

## Required repository changes before production activation

1. Split the current `lovable-audio-sync.py` into prepare and deploy phases or refactor it into an explicit state machine.
2. Reuse `prepare-audio-track-v3.py` for canonical conversion and mastering gates.
3. Change the timer from 30 seconds to 15 seconds only after preparation is made non-disruptive.
4. Add resource controls to the preparation service.
5. Replace the current post-restart `after > before` check with a measured real-time pacing ratio.
6. Add full-file decode, duration, and packet timestamp validation.
7. Persist candidate manifests and revision-specific failure reasons.
8. Keep automatic retry disabled for a failed revision.
9. Add Lovable deployment-status callback only after the Oracle pipeline itself is certified.
10. Re-enable the production timer only after a shadow test proves preparation causes no live pacing degradation.

## Production acceptance test

Before enabling automatic deployment, run one approved test revision in shadow mode:

- Oracle detects and downloads it.
- Oracle processes it under the resource cap.
- Oracle validates it completely.
- The live master is not restarted.
- Confirm master pacing remains 0.98–1.02 throughout processing.

Then perform one controlled cutover with automatic rollback armed. Production auto-deploy is enabled only after that test passes.

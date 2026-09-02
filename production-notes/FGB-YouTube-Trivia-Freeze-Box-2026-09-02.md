# FGB YouTube trivia small-box protection — verified production state

**Verified:** 2026-09-02 approximately 03:29 America/Chicago  
**Scope:** YouTube branch only; master encoder and Rumble unchanged.

## Active no-expansion architecture

The production YouTube branch now uses the existing packet router with a dynamically refreshed static freeze-frame card instead of the prior full-screen emergency card.

During an authoritative trivia question phase:

- Rumble remains on the live master program and displays the real trivia question/answers.
- YouTube switches at an H.264 keyframe from the live program to a recent 1280x720 freeze-frame snapshot.
- Only the reconciled trivia question rectangle is visibly replaced on that snapshot:
  - x=480
  - y=200
  - width=640
  - height=360
- The replacement copy reads `TRIVIA IS LIVE ON RUMBLE` with supporting viewer instructions.
- When the question phase clears, YouTube switches back to the live program at a keyframe.
- No continuous second video encode and no additional Oracle instance are required.

The intended tradeoff is that pixels outside the 640x360 trivia rectangle are a frozen snapshot during the protected question interval. They are not a live compositor feed. This avoids new Oracle compute while preventing the real question from appearing on YouTube.

## Dynamic card generation

Active generator: `/usr/local/bin/fgbears-youtube-freeze-card-refresh`

The v2 generator:

- requires the authoritative routing payload and exact 480,200,640x360 mask geometry;
- refuses capture while `phase=question` or `youtubeMaskActive=true`;
- permits a non-question ad/transition frame because the trivia rectangle is fully replaced;
- rechecks routing after encoding and discards the candidate if a question became active;
- captures one frame from the existing reusable UDP source;
- encodes a one-second H.264 baseline 1280x720/yuv420p asset at low process/IO priority;
- atomically replaces `/var/lib/fgbears-live/youtube-freeze-card.h264`;
- is scheduled by `fgbears-youtube-freeze-card-refresh.timer` at :18, :38, and :58 before the :20, :40, and :00 trivia anchors.

## Production activation — PASSED

GitHub Actions run `33608883670` completed successfully.

Observed values:

- `result=updated at=2026-09-02T08:28:36Z bytes=131085 geometry=480,200,640,360 mode=nonquestion-freeze-v2`
- master PID remained `2112260`
- Rumble relay PID remained `2199880`
- YouTube router PID remained `2209020`
- YouTube RTMPS remained established
- card was hot-reloaded without restarting the router
- refresh timer active and enabled
- activation result: `PASS`

## Live question-cycle verification — PASSED

Read-only GitHub Actions run `33609007668` verified the active production path after the v2 card was published.

Observed values:

- card probe: `h264,1280,720,yuv420p`
- `LIVE_QUESTION_CYCLE=live_to_small_card_to_live`
- master PID unchanged: `2112260`
- Rumble relay PID unchanged: `2199880`
- YouTube router PID unchanged: `2209020`
- YouTube RTMPS established: yes
- freeze-card timer active/enabled
- `SMALL_BOX_LIVE_VERIFICATION=PASS`

## Safety / rollback

The previous full-screen emergency card remains the conceptual fallback if dynamic card generation is unavailable before a future deployment, but the active dynamic card is now the verified small-box freeze-frame version.

The YouTube router remains isolated from the master and Rumble branches. Do not restart or modify `fgbears-live.service` or `fgbears-rumble-relay.service` as part of YouTube trivia-card maintenance.

If the hot-reload router becomes unhealthy, restore the previously verified emergency YouTube router/direct-relay rollback procedure from `production-notes/FGB-YouTube-Trivia-Overlay-2026-09-01.md`.

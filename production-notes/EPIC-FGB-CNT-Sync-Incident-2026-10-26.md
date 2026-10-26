# EPIC FGB + CNT trivia timing incident — 2026-10-26

## Reported behavior
The public website and YouTube initially show matching trivia phases, then grow progressively out of alignment during a game. FGB and CNT must retain independent channel branding, configurations, media and YouTube destinations while receiving shared timing fixes. No Lovable or new project.

## Verified infrastructure
- OVH contains separate healthy capture containers: `fgb-transport-youtube-1` and `epic-cnt-capture`.
- Their live capture URLs match their own channels. No container or encoder was restarted by this investigation.
- FGB's 117.35-second pacing sample advanced output media time by 117.58 seconds at around 30 fps, with zero new drops, duplicates or restarts. Sustained FGB encoder slowdown was NOT detected.
- CNT's independent 31-second sample advanced media time by about 30.783 seconds against roughly 30.96 seconds of elapsed time; the 82-frame cumulative drop counter did not increase and container restarts stayed at zero. Sustained CNT encoder slowdown was NOT detected in that window.
- FGB website feed declares `delaySeconds: 21.25`. A fixed display offset alone cannot compensate if individual YouTube players buffer by different or changing amounts.
- Browser-based YouTube playback probe could not load playable media, and read-only YouTube latency-mode API queries could not authenticate using the existing GitHub or OVH archive credentials. Do not claim current YouTube latency mode is known.
- One website/source API snapshot returned differing game phases; cross-endpoint reads were not simultaneous and cannot by themselves prove a specific website defect.

## Changes applied
1. Added `.github/workflows/audit-live-trivia-drift.yml`, with FGB and CNT media-clock telemetry, periodic wall-clock comparisons, and hourly read-only audit scheduling.
2. Added `.github/workflows/inspect-cnt-capture-clock.yml` to verify CNT's own capture browser and process/progress files without interruption.
3. Added `.github/workflows/audit-fgb-youtube-latency.yml` and `.github/workflows/read-fgb-latency-from-ovh.yml` as read-only active-latency-preference probes. Both lacked applicable OAuth credentials; no setting was modified.

## Remaining root-cause isolation and corrective work
1. Obtain active YouTube broadcast latency settings for each channel from authorized YouTube Studio/API access. Prefer low-latency for trivia, testing under production load; ultra-low requires special consideration because it raises buffering risk. Existing live broadcasts may restrict changing this setting.
2. Capture actual viewer-visible question transitions and compare to the corresponding server-issued `phaseStartsAt` and `phaseEndsAt` across multiple complete 10-minute games. External YouTube buffering varies by viewer; a single global constant is not an exact solution.
3. Make both website and broadcast presentations derive from immutable server game-start/phase timestamps. Never drive question progression by counting timer callbacks in a browser.
4. Where per-viewer YouTube playback can be measured reliably, expose viewer-specific latency/catch-up guidance without making client-provided timestamps authoritative for scoring or payments.
5. Keep game response eligibility server-authoritative and ensure variable video buffering cannot silently shorten the advertised response window. Any policy changes need compatibility checks against financial ledger/scoring logic.
6. Validate separately for FGB and CNT, preserving channel-specific branding and destinations. Roll back immediately on regression.

## Scope and safety
No gameplay, balances, scoring, beneficiary selections, or live broadcast settings were modified. The read-only monitors do not restart services or change encoder configuration. The permanent end-to-end sync fix is not yet verified or deployed to the website or YouTube player; the production website source is not writable through the connected GitHub repository, and there is no usable YouTube API authorization for active broadcast settings.

## October 26 follow-up — additional work
- Created `.github/workflows/audit-public-trivia-phase-alignment.yml` to compare the public broadcast and website game-screen endpoints via simultaneous reads. In an initial 90-sample run, four comparisons had directly comparable questions from the same game. In all four, the website showed one question earlier than the broadcast, consistent with the configured 21.25-second delay. The rest covered pool votes/intermission/scoreboard; the test does not prove or exclude progressive intra-game site clock drift.
- Added hourly read-only website/broadcast phase checks at minute 23, complementing hourly FGB and CNT encoder media-clock checks at minute 17. Neither check changes live playback or records.
- Created a channel-agnostic relative-live-buffer guard in existing `mrkenapierce/ChatGPT`, file `epic-website-sync/source/yt-live-relative-drift-guard.mjs`. Once website-integrated, it measures extra YouTube player buffer relative to a viewer-confirmed synchronized starting point and can restore the original offset using YouTube's supported IFrame player `seekTo` method, gated by explicit arming, sustained samples and cooldown.
- Added a Node regression test and GitHub verification workflow. Both immutable timeline and new live player guard tests passed in GitHub run `40340405436`.
- The player guard is STAGED ONLY; it is not wired into the actual published website. GitHub/OVH controls capture containers, but this connected GitHub repository does not contain a verified deployment route into the site's production application. The next necessary step is production website integration and validation.
- Current YouTube broadcast latency preference could not be authenticated; it remains unknown. No YouTube latency setting was changed.

### Full acceptance test after website integration
For both FGB and CNT, observe the stream over at least two consecutive complete trivia games. Correlate server phase timestamps, website phase, YouTube IFrame currentTime/duration/state, and actual visual question/reveal times. Verify that buffering does not cause progressively worsening alignment and that corrections do not alter player answer deadlines, scoring, ledgers, beneficiary decisions or independent stream branding and destinations.

### Tested integration package refinement
- Added an explicit production integration contract in `mrkenapierce/ChatGPT/epic-website-sync/PLAYER_DRIFT_INTEGRATION.md`, including YouTube IFrame API requirements, channel isolation, viewer opt-in, release criteria, and the verified missing website-deployment link.
- Player-side guard now detects unexpected/manual position jumps and disarms rather than overriding viewers who intentionally rewound their livestream.
- Updated tests covering manual rewind plus earlier baseline, correction, pause, buffering, cooldown and stream-reset cases passed in GitHub workflow run `40341325197`.

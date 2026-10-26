# FGB → CNT shared-stream synchronization contract
Updated: 2026-10-25. Scope: GitHub/OVH transport and observation only; no Lovable or production FGB changes.

## Source-of-truth rule
- FGB and CNT must use the same **live trivia game-screen data** from `/api/public/fgbears/game-screen`, including question text, answer choices, answer-reveal timing, countdowns, and My $0.02 shared program logic.
- The CNT capture URL stays `https://epiccontentcreatorgrants.org/channels/cruisenewstrivia/broadcast`. FGB stays on its own `/fgb-broadcast?target=youtube` URL.
- The CNT browser must render the shared `[data-testid=broadcast-scene]` presentation (as observed during the 2026-10-25 lifecycle run). A separate or stale trivia implementation is not an acceptable fallback.
- CNT-specific **cruise news, channel identification, audio, visual assets and YouTube stream key/destination** remain independently configured. Do **not** mirror the FGB brand, Bears stories, output keys, or FGB-specific media.
- Never use a raw copy of FGB's stream video as CNT's trivia feed. Both channels must display the shared live trivia state independently, without coupling encoder uptime.

## Every future shared-stream change
1. Classify whether the change is shared (trivia scheduling, question/answer UX, timers, graphic rules, qualifying-play math, shared crawl, or transport common capture behavior) versus FGB-specific.
2. For a shared change, update the **canonical upstream component/data source** used by *both* channel pages, rather than patching only `/fgb-broadcast`. If the change originates in a separate website codebase, that codebase must apply it to both routes; GitHub cannot silently synchronize web application code that isn't in this repository.
3. Run the `CNT shared trivia question lifecycle observer` against the CNT capture browser. Confirm an identical active source prompt, answer reveal, and advancing CNT FFmpeg frames; verify that FGB container remains running.
4. Check CNT's actual YouTube viewer output/preview separately; a successful browser/encoder check alone **does not** prove pixels made it through YouTube.
5. Do not roll out an FGB transport change as a shared-stream change unless CNT's transport settings and the CNT-only deployment runbook are also reviewed. Deploy channels separately and keep FGB live.

## Evidence and enforcement
- GitHub Actions: `.github/workflows/cnt-question-lifecycle.yml`. Runs on changes to the CNT/FGB transport paths on the CNT preflight branch and may be dispatched manually. When a question was observed from the shared feed, the check fails if CNT does not render the corresponding prompt or answer reveal.
- This guard detects drift but **does not** edit the website or autonomously deploy changes. Future central website UI changes need a shared-component implementation and release check at their source.
- The October 25 evidence showed matching CNT and shared feed prompts with about 3.1 s display lag; answer reveal observed; frames advanced. YouTube public playback could not be independently sampled because the public sampling client encountered YouTube's sign-in restriction.

## Non-disruption requirements
- Never restart FGB's encoder, change its stream key, or reboot the VPS as part of CNT parity work.
- Never restart CNT's encoder just to pick up a frontend site change; prefer verified page-only refresh when genuinely needed.
- No new Lovable project. No backend/database edits. No replacement of existing public URLs.

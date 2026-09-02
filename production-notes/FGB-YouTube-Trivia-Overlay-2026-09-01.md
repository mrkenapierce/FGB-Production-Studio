# FGB YouTube-only trivia overlay — production status

**Original work:** 2026-09-01  
**Current authoritative status:** 2026-09-02 after no-freeze live-cycle verification

## CURRENT AUTHORITATIVE REQUIREMENT

The YouTube picture must **not freeze during trivia**. The RSS/news upper-third and the messaging crawl must remain functional and visibly moving at all times, including while a trivia question is active.

A whole-frame packet switch to a pre-encoded/static card does not satisfy this requirement, even if the artwork itself only occupies the trivia panel, because the encoded YouTube frame is replaced as a whole. The previous freeze-card/router approach is therefore **deprecated and prohibited for production**.

The desired final behavior is:

- Rumble: unchanged live master program, including the real trivia question.
- YouTube outside a question: unchanged live master program.
- YouTube during a fresh authoritative question: replace only the production trivia panel with the approved `yt_rumble_trivia_redirect` creative while every other live pixel — particularly RSS/news and crawl — continues advancing normally.
- Trigger: `trivia.youtubeMaskActive === true`, `phase === "question"`, and non-stale state.
- Routing failure, stale state, or malformed state: fail open/transparent to live video.

## CURRENT PRODUCTION STATE — NO FREEZE

The freeze router was removed from the active YouTube path and the canonical continuous direct relay was restored in guarded workflow run `33613628467`.

Verified after the handoff:

- `fgbears-live.service` remained running without restart.
- `fgbears-rumble-relay.service` remained running without restart.
- `fgbears-youtube-relay.service` is the active continuous YouTube branch.
- YouTube RTMPS was established and remained stable through the post-cutover hold.
- `fgbears-youtube-router.service` is disabled/inactive.
- `fgbears-youtube-freeze-card-refresh.timer` is disabled/inactive.
- `fgbears-youtube-audio-watchdog.timer` is enabled again for the canonical direct relay.

A real question-cycle verification then passed in workflow run `33613808963`. During an authoritative state of `phase="question"`, `youtubeMaskActive=true`, `stale=false`:

- master program clock advanced exactly 5,000,000 microseconds during the 5-second sample;
- RSS/news health remained active with a non-empty live message;
- crawl health remained OK;
- the continuous direct YouTube RTMPS transport remained established;
- the freeze router remained inactive;
- result: `NO_FREEZE_LIVE_CYCLE=PASS`.

**Current tradeoff:** because the active direct relay is copy-only and performs no pixel composition, YouTube currently shows the trivia question. This is intentional as the safe interim state: continuously moving RSS/crawl takes precedence over the rejected full-frame freeze solution.

## PRODUCTION GEOMETRY

The production middle trivia/ad panel is exactly:

- `x=462`
- `y=104`
- `width=798`
- `height=470`
- bounds `(462,104)-(1260,574)`

The RSS/news band occupies `y=0..103`. The crawl begins at `y=574`. Therefore the production trivia panel is exactly the safe middle region between those two continuously moving bands.

Lovable's routing contract has been reconciled to this geometry and identifies the locked full redirect creative as `yt_rumble_trivia_redirect`.

## EXACT APPROVED CREATIVE

The repository's canonical exact-card builder is:

`services/fgbears-live/tools/build-youtube-rumble-trivia-card.py`

It renders the locked 1280x720 YouTube-to-Rumble creative, including the QR code and approved visual copy. When used inside the final compositor, the complete creative is to be treated as one immutable asset and proportionally scaled to `798x449`, centered at `x=462,y=114` inside the `798x470` production panel. Individual elements must not be reconstructed or independently resized.

## CURRENT-HOST CAPACITY TESTS — FINAL RESULT

Three isolated, non-publishing tests were performed while production services remained live.

### 1. Full moving software compositor

Workflow: `benchmark-youtube-live-compositor-v1.yml`, run `33613350129`.

Result: `ENCODE_REALTIME_MULTIPLIER=0.675x` — insufficient for a continuous 1.0x live stream, before reserving a safety margin.

### 2. Static middle/background with only RSS and crawl moving

Workflow: `benchmark-youtube-dynamic-bands-v1.yml`, run `33614228597`.

The actual local overlay sources were measured as:

- RSS/news: `1280x104`, 25 fps
- crawl: `1280x139`, 25 fps

Result: `DYNAMIC_BANDS_REALTIME_MULTIPLIER=0.552x` — also insufficient.

### 3. Hardware encoder probe / VAAPI

The VM exposes `/dev/dri/card0` and `/dev/dri/renderD128`, and its FFmpeg build lists VAAPI encoder support. However an actual isolated H.264 VAAPI encode failed before encoding with:

- `Failed to initialise VAAPI connection`
- `unknown libva error`
- `Failed to set value '/dev/dri/renderD128' for option 'vaapi_device': Input/output error`

Therefore the current Oracle VM does **not** provide a usable hardware H.264 encode path for this compositor.

### Capacity conclusion

The existing production VM cannot safely perform the required live partial-frame YouTube composition in software, and its exposed DRM device does not provide a usable VAAPI encode path. Do not put a real-time YouTube compositor on this source VM.

## REQUIRED FINAL ARCHITECTURE

The correct final architecture remains a separate YouTube-only compositor host:

1. The production VM emits a copy-only encoded source branch; master and Rumble remain untouched.
2. The compositor receives that branch, keeps the full moving live frame, and replaces only `(462,104)-(1260,574)` during the authoritative question interval.
3. The compositor uses the locked `yt_rumble_trivia_redirect` creative as the panel source.
4. RSS/news and crawl remain part of the continuously moving live picture and are never substituted with a static full frame.
5. The compositor publishes the resulting YouTube-only stream.
6. Failure must fall back to the continuous direct relay, never to the deprecated full-frame freeze router.

The repository already contains the architectural starting point:

- `services/fgbears-live/bin/youtube-question-mask.py`
- `services/fgbears-live/bin/youtube-offhost-compositor.sh`
- `services/fgbears-live/bin/youtube-compositor-source-relay.sh`

These must be reconciled to the authoritative `462,104,798x470` geometry and exact locked creative before final deployment.

## FREEZE PATHS PERMANENTLY DEPRECATED

The following activation/deployment workflows have been replaced with blocked tombstones so a manual run cannot silently restore the rejected whole-frame freeze behavior:

- `activate-youtube-exact-card-v4.yml`
- `activate-youtube-exact-card-v4b.yml`
- `activate-youtube-exact-card-v4c.yml`
- `activate-youtube-freeze-box-card.yml`
- `deploy-youtube-freeze-box.yml`
- `emergency-cutover-youtube-trivia-router.yml`
- `emergency-cutover-youtube-trivia-router-v2.yml`

Historical packet-router verification remains useful as diagnostic history only. It is not an approved production solution going forward.

## COST / PROVISIONING BOUNDARY

Free separate compute should be attempted first. Do not provision paid compute without separate explicit authorization. Previous Oracle A1 free-capacity attempts in `us-chicago-1` were blocked by capacity, and the current tools do not have Oracle Compute provisioning authority.

## SECURITY

Never print or expose YouTube/Rumble ingest targets, stream keys, SSH private keys, or environment secrets in Actions logs or production notes. Historical ingest credentials exposed in an older public diagnostic log should continue to be treated as compromised until rotated; they are intentionally not reproduced here.

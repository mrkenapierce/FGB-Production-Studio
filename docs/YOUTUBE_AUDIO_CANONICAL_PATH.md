# FGBears YouTube Audio — Canonical Production Path

Effective: 2026-09-01 (America/Chicago)

## Production invariant

The YouTube branch must preserve the exact encoded program emitted by the shared FGBears master.

Canonical path:

`shared master -> MPEG-TS loopback UDP :1939 -> FFmpeg -c copy -> YouTube RTMPS`

The YouTube relay must not:

- decode or re-encode audio;
- decode or re-encode video;
- pass AAC through a GStreamer parser/muxer;
- regenerate or re-clock audio timestamps in a platform-specific router;
- run a YouTube-only compositor or packet router in the live transport;
- restart the shared master or Rumble relay as part of YouTube recovery.

The sibling Rumble branch remains independent on loopback UDP :1940.

## Why this is locked

The September 1, 2026 incident was isolated to YouTube while Rumble remained clean. The experimental YouTube packet-router path demuxed the master MPEG-TS, parsed AAC, re-muxed it through GStreamer, and then copy-remuxed the result again through FFmpeg before YouTube ingest. That additional YouTube-only timestamp/mux layer was the unique transport difference and therefore the regression surface.

The production repair replaced that branch with the proven direct FFmpeg copy/remux relay. The repair verification confirmed the relay was FFmpeg `-c copy`, the RTMPS socket was established, the YouTube-bound source audio passed its objective health gate, and no new audio timestamp errors were present.

## Monitoring and automatic recovery

### Oracle local guard — every minute

`fgbears-youtube-audio-watchdog.timer` runs `fgbears-youtube-audio-watchdog.service` once per minute.

The watchdog verifies:

1. the shared master is active;
2. the YouTube relay is active;
3. the relay process is the canonical FFmpeg `-c copy` process and is not the retired packet router/GStreamer path;
4. the relay owns an established RTMPS/TCP 443 connection;
5. recent YouTube-relay logs contain no audio timestamp/DTS regressions;
6. the exact MPEG-TS source feeding YouTube passes the audio-health sampler.

For an isolated YouTube transport fault, the watchdog restarts only `fgbears-youtube-relay.service`. A two-restarts-per-30-minutes circuit breaker prevents restart loops. Shared-source warnings are recorded but never cause this watchdog to restart the master or Rumble.

### Viewer-side guard — every 15 minutes

`.github/workflows/fgbears-youtube-public-audio-guard.yml` probes the public YouTube livestream from the viewer side. It requires two consecutive failed probes before recovery. When recovery is required, it restarts only the YouTube relay, verifies that the master and Rumble PIDs did not change, and then performs a post-recovery viewer-side audio check.

## Supported recovery order

1. Detect whether the shared YouTube-bound source is healthy.
2. If the defect is YouTube-only, restart only the YouTube copy/remux relay.
3. Verify canonical relay process + RTMPS socket.
4. Verify viewer-side YouTube audio.
5. Never restart the master or Rumble solely to repair a YouTube-only audio incident.

## Retired architecture

The GStreamer packet router, YouTube-only live compositor experiments, router deployment generations, one-off relay repair workflows, and duplicate audio verification workflows are retired from active GitHub Actions. Their history remains recoverable through Git history, but they must not be reactivated in production without a new design review and a transport-level A/B test proving that audio timestamps remain untouched.

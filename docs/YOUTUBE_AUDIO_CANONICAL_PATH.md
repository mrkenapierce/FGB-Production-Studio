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

The production repair replaced that branch with the direct FFmpeg copy/remux relay. The repair verification confirmed the relay was FFmpeg `-c copy`, the RTMPS socket was established, the YouTube-bound source audio passed its objective health gate, and no new audio timestamp errors were present.

## Monitoring and automatic recovery

### Layer 1: Oracle local guard — every minute

`fgbears-youtube-audio-watchdog.timer` runs `fgbears-youtube-audio-watchdog.service` once per minute.

The watchdog verifies:

1. the shared master is active;
2. the YouTube relay is active;
3. the relay process is the canonical FFmpeg `-c copy` process and is not the retired packet router/GStreamer path;
4. the relay owns an established RTMPS/TCP 443 connection;
5. recent YouTube-relay logs contain no audio timestamp/DTS regressions;
6. the exact MPEG-TS source feeding YouTube passes the audio-health sampler.

For an isolated YouTube transport fault, the watchdog restarts only `fgbears-youtube-relay.service`. A two-restarts-per-30-minutes circuit breaker prevents restart loops. Shared-source warnings are recorded but never cause this watchdog to restart the master or Rumble.

### Layer 2: GitHub supervisor — every 15 minutes

`.github/workflows/fgbears-youtube-audio-supervisor.yml` verifies the monitoring layer itself from outside the Oracle instance. It checks that the watchdog timer is enabled and active, runs one watchdog cycle, confirms the status record is fresh, verifies the canonical FFmpeg copy relay and established RTMPS socket, and confirms that the master and Rumble PIDs remain unchanged.

If the watchdog timer has stopped or been disabled, the supervisor restores the timer. The supervisor does not contain an independent stream-restart algorithm; all YouTube recovery remains centralized in the local watchdog so there is only one correction authority.

### Deliberately rejected: unauthenticated viewer scraping

An automated public-playback probe was tested and retired because a probe-access failure can be unrelated to stream audio. Probe infrastructure failure must never be treated as evidence that production audio is bad, and it must never be allowed to trigger a stream restart. Public playback can still be used for manual verification when needed, but it is not an automatic correction signal.

## Supported recovery order

1. Measure the exact MPEG-TS source feeding the YouTube relay.
2. Verify the canonical YouTube relay process and RTMPS connection.
3. Inspect recent YouTube relay timestamp/DTS errors.
4. If the fault is isolated to YouTube, restart only the YouTube copy/remux relay.
5. Reverify relay process, socket, source audio, and unchanged master/Rumble PIDs.
6. If the evidence points to a shared-source issue, record/escalate it without using the YouTube watchdog to restart the shared master.

## Retired architecture

The GStreamer packet router, YouTube-only live compositor experiments, router deployment generations, one-off relay repair workflows, duplicate audio verification workflows, and the unauthenticated public-playback auto-repair probe are retired from active GitHub Actions. Their history remains recoverable through Git history, but they must not be reactivated in production without a new design review and a transport-level A/B test proving that audio timestamps remain untouched.

## Deployment invariant

Full installs and future rebuilds must keep `FGB_YOUTUBE_PACKET_ROUTER_ENABLE=0`, install and enable the YouTube audio watchdog, and preserve `youtube-relay.sh` as a direct FFmpeg `-c copy` implementation. Repository tests fail if the canonical relay regains the retired router/GStreamer/re-encode path.

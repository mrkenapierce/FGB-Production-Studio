# FGB Audio Mastering Protocol

## Canonical profile

All Football's Greatest Bears production episodes must use the offline audio profile `fgb-podcast-v2-mastered` before they are eligible for the livestream playlist.

The mastering stage is deliberately offline. The live master encoder and platform relays must not add speech DSP, loudness normalization, audio re-encoding, or platform-specific audio processing. The live program copies the already-mastered AAC track, and the YouTube relay remains a transparent `-c copy` transport.

## Signal chain

The canonical speech chain is:

1. 70 Hz second-order high-pass filter for low-frequency rumble and handling noise.
2. 15.5 kHz second-order low-pass filter for unnecessary high-frequency energy.
3. Gentle low-mid EQ reduction centered near 180 Hz (`-1.5 dB`, Q `0.9`) to reduce muddiness.
4. Mild speech-presence lift centered near 3.2 kHz (`+1.25 dB`, Q `0.8`) for intelligibility.
5. Conservative de-essing (`deesser i=0.15, m=0.35, f=0.5`).
6. Conservative RMS compression at `2.25:1`, with 12 ms attack and 180 ms release.
7. Two-pass EBU-style loudness normalization to:
   - integrated loudness: `-14 LUFS`
   - loudness range target: `11 LU`
   - true-peak target: `-1.5 dBTP`
8. Delivery encoding: AAC at 192 kb/s, 48 kHz, stereo.

The general-purpose chain intentionally does not apply aggressive broadband denoising or a noise gate. Those processes are source-dependent and can cause pumping, clipped word endings, and speech artifacts when applied blindly to an archival library.

## Verification gate

A mastered production file is eligible only when its adjacent `.audio-profile.json` marker proves all of the following:

- profile is `fgb-podcast-v2-mastered`
- `mastered` is `true`
- the mastering chain is recorded and non-empty
- AAC delivery profile is 192 kb/s, 48 kHz, stereo
- marker SHA-256 matches the actual media file
- measured integrated loudness is within `0.8 LU` of `-14 LUFS`
- measured true peak does not exceed `-1.0 dBTP`

`fgbears-validate` enforces this gate. A loudness-only v1 asset cannot pass as a v2 mastered asset.

## Ingest invariant

`fgbears-add-episode` must invoke only `/usr/local/bin/fgbears-normalize`. No fallback or legacy normalizer is permitted. The result must pass the full media-library validator before playlist activation.

## Live transport invariant

Do not move this mastering chain into `start-stream.sh`, `youtube-relay.sh`, or `rumble-relay.sh`.

The stable live architecture is:

`mastered media -> shared master program -> loopback MPEG-TS mirrors -> platform copy/remux relays`

For YouTube specifically:

`shared master -> UDP 127.0.0.1:1939 -> FFmpeg -c copy -> YouTube RTMPS`

This separation is a production reliability requirement, not an optimization preference.

## Source-specific restoration

If an individual source has severe clipping, hum, broadband noise, dropouts, or other damage already baked into the recording, treat that episode as a source-restoration exception. Restore it offline from the best available original/master, then run the restored result through this canonical v2 mastering profile. Do not weaken or bypass the profile to accommodate a damaged source.

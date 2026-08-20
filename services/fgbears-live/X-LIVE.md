# FGBears Live on X

Football's Greatest Bears is designated to stream to the X account **@epic501c3**.

FGBears Live uses the existing Oracle/FFmpeg production engine and encodes the finished program once. FFmpeg's tee muxer distributes the same H.264/AAC program to YouTube and, when enabled, an X Live Studio RTMP/RTMPS Source created under **@epic501c3**.

## Safety boundary

YouTube remains the primary output. The YouTube tee leg uses `onfail=abort`; the X leg uses `onfail=ignore`. A failed, timed-out, or unavailable X livestream therefore cannot terminate the YouTube broadcast. FIFO isolation gives each destination its own output thread and recovery loop.

## Encoder compatibility

The shared X-compatible output uses:

- H.264 High Profile
- 1280x720
- 24 fps
- approximately 4 Mbps video
- AAC stereo, 48 kHz, 128 kbps
- 2-second keyframes

X accepts H.264/AVC and AAC-LC up to 128 kbps. The existing FGB 720p/24 fps program is retained to avoid destabilizing the working YouTube channel; X recommends testing the selected encoder configuration before public use.

## Create the reusable X Source for @epic501c3

While signed in to **@epic501c3** in X Live Studio:

1. Open the Sources tab.
2. Create a new RTMP Source.
3. Select the region closest to the Oracle encoder.
4. Copy the RTMPS URL and RTMP Stream Key from that Source.
5. Use a private test livestream first.

The Source credentials determine which X account receives the encoder feed, so the credentials must come from **@epic501c3**. A public handle alone cannot be converted into a stream key.

## Enable X on Oracle

After deployment, run:

```bash
sudo fgbears-configure-x
```

The helper is hard-bound operationally to **@epic501c3** and prompts for that account's RTMPS URL and stream key. The key is written only to `/etc/fgbears-live/stream.env`, which remains root-controlled, and the service is restarted once.

To disable X without affecting YouTube:

```bash
sudo fgbears-configure-x --disable
```

## Verify

```bash
sudo systemctl status fgbears-live.service
sudo fgbears-stream-status
```

Do not print the full FFmpeg command line because RTMP stream keys are present in output URLs.

## X livestream sessions

The reusable RTMP Source may be used for successive X livestreams. X manages the public livestream/broadcast object separately from the RTMP Source, so the Oracle transport can stay configured while X-side livestream sessions are created or scheduled as required by the platform.

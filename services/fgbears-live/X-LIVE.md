# FGBears Live on X

FGBears Live uses the existing Oracle/FFmpeg production engine and encodes the finished program once. FFmpeg's tee muxer distributes the same H.264/AAC program to YouTube and, when enabled, an X Live Studio RTMP/RTMPS Source.

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

X Live Studio supports H.264, AAC up to 128 kbps, High or Main profile, and 24 fps. X recommends 3-second keyframes; the existing 2-second FGB setting is retained because it also satisfies YouTube's production requirements and avoids destabilizing the working YouTube channel.

## Create the reusable X Source

In X Live Studio:

1. Create a new livestream.
2. Create a Source in the region closest to the Oracle encoder.
3. Copy the RTMPS URL and Stream Key.
4. Use a private test livestream first.

A Source is reusable across multiple X livestreams. X currently limits an individual livestream to 24 hours, so the public X livestream object must be recreated or scheduled for the next period even though the Oracle encoder and Source configuration stay the same.

## Enable X on Oracle

After deployment, run:

```bash
sudo bash /opt/fgbears-live/bin/configure-x.sh
```

Paste the RTMPS URL and stream key when prompted. The key is written only to `/etc/fgbears-live/stream.env`, which remains root-controlled, and the service is restarted once.

To disable X without affecting YouTube:

```bash
sudo bash /opt/fgbears-live/bin/configure-x.sh --disable
```

## Verify

```bash
sudo systemctl status fgbears-live.service
sudo fgbears-stream-status
```

Do not print the full FFmpeg command line because RTMP stream keys are present in output URLs.

## X 24-hour operating rule

X Live Studio states that each livestream has a maximum duration of 24 hours. The reusable Source can remain the same, but a new X livestream must be created for the next period. X's public developer API documentation does not currently expose a Live Studio endpoint for programmatically creating those livestream objects, so the transport layer is automated while the X livestream-object rollover remains an X account operation.

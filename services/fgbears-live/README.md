# FGBears TV 24/7 Replay Stream

Zero-license-cost infrastructure for a genuine YouTube encoder livestream that continuously rotates prerecorded Football's Greatest Bears episodes. GitHub stores the system; an Oracle Cloud Always Free Ubuntu Arm VM runs FFmpeg. The YouTube stream key is never committed.

## Broadcast identity

Recommended public title:

`FGBears TV LIVE | 24/7 Chicago Bears Episodes & Commentary`

Required disclosure in the title, description, thumbnail, or persistent overlay:

`FGBears TV • 24/7 REPLAY`

The transport is live; the programming is prerecorded.

## Architecture

```text
normalized FGBears MP4 episodes
          |
          v
Oracle Always Free Ubuntu Arm VM
          |
          v
FFmpeg concat loop (stream copy; no continuous re-encoding)
          |
          v
YouTube RTMPS encoder ingest
```

## Oracle instance specification

Use only resources marked **Always Free eligible**:

- Image: Ubuntu 24.04 or 22.04, Arm/aarch64
- Shape: `VM.Standard.A1.Flex`
- Allocation: 2 OCPUs and 12 GB RAM
- Boot volume: 150 GB or less, leaving the tenancy below its free 200 GB block-volume allowance
- Public IPv4 address: enabled
- Ingress: SSH TCP 22 only, restricted to the administrator's IP when practical
- No inbound streaming port is required; FFmpeg initiates the outbound RTMPS connection

Free capacity is not guaranteed in every home region. Oracle may reclaim instances it classifies as idle. A continuous stream should create meaningful CPU/network activity, but free-tier continuity is not guaranteed.

## Automated installation

Paste `cloud-init/ubuntu.yaml` into Oracle's cloud-init/user-data field when creating the instance. It clones the public production repository and installs the service.

Manual equivalent:

```bash
git clone https://github.com/mrkenapierce/FGB-Production-Studio.git
sudo bash FGB-Production-Studio/services/fgbears-live/bin/install.sh
```

Installation creates:

- `/srv/fgbears-live/media` — normalized episodes
- `/srv/fgbears-live/incoming` — temporary uploads
- `/srv/fgbears-live/playlist.ffconcat` — generated sequence
- `/etc/fgbears-live/stream.env` — root-controlled stream configuration
- `fgbears-live.service` — persistent FFmpeg relay
- `fgbears-live-health.timer` — five-minute recovery check

## Secure YouTube activation

In YouTube Studio, create an encoder stream using a reusable custom stream key. Use **normal latency**, turn **Auto-start on**, and leave **Auto-stop off** so a brief server restart does not intentionally close the event.

On the server, edit the protected configuration:

```bash
sudo nano /etc/fgbears-live/stream.env
```

Replace only the placeholder value. Never put the key in GitHub, a screenshot, email, or chat.

```text
YOUTUBE_STREAM_KEY=your-private-key
```

Then restrict and verify permissions:

```bash
sudo chown root:fgbears /etc/fgbears-live/stream.env
sudo chmod 640 /etc/fgbears-live/stream.env
```

## Add episodes

Upload owned/authorized master files to the VM using SFTP or SCP, then run:

```bash
sudo fgbears-add-episode /srv/fgbears-live/incoming/FGBears-Episode-01.mp4
```

The command performs one-time normalization, validates the output, rebuilds the numerically sorted playlist, and restarts the service if it is enabled.

Standard relay format:

- 1280x720
- 30 fps constant frame rate
- H.264 High Profile
- 4 Mbps video
- AAC stereo, 48 kHz, 128 kbps
- keyframe interval: 2 seconds

The live output applies a voice-forward podcast chain to every episode: low-rumble
and light background-noise reduction, warm/presence EQ, de-essing, gentle speech
compression, EBU R128 normalization to -16 LUFS, and a -1.5 dBTP ceiling. The
processed output is AAC stereo at 48 kHz and 160 kbps. This happens at broadcast
time, so existing and newly added episodes receive the same treatment.

The live encoder uses one local, fixed-rate graphic rather than HTTP video feeds.
The advertising frame is the sole video clock at 30 fps, while the Lovable crawl is
drawn directly from reloadable text files. Graphics can no longer become the
master clock or stall the broadcast. A five-minute watchdog checks FFmpeg's real
output progress and recovers the service only if output stops advancing; slow
encoding and ordinary advertising updates do not restart the live video.

At approximately 4.13 Mbps total, continuous outbound transfer is roughly 1.34 TB per 30-day month, comfortably below a 10 TB allowance. Actual usage varies.

## Start the channel

After at least one episode and the private stream key are installed:

```bash
sudo systemctl enable --now fgbears-live.service
sudo systemctl status fgbears-live.service
sudo journalctl -u fgbears-live.service -f
```

Verify the preview in YouTube Live Control Room before making the watch page public.

## Operations

```bash
# Service health
sudo systemctl status fgbears-live.service

# Recent logs
sudo journalctl -u fgbears-live.service --since '30 minutes ago'

# Rebuild the playlist
sudo fgbears-rebuild-playlist

# Validate every normalized episode
sudo fgbears-validate /srv/fgbears-live/media

# Restart after an intentional change
sudo systemctl restart fgbears-live.service
```

Systemd automatically restarts FFmpeg after a crash or connection failure. The timer performs a second recovery check every five minutes.

## YouTube archive behavior

A stream that runs longer than 12 hours may not be archived. That is intentional for this linear replay channel because each source episode remains separately published. The persistent live event should not be treated as the archive of record.

## Cost boundary

There is no software license charge. Oracle's Always Free resources can avoid a hosting bill only while the account, instance shape, storage, and transfer remain within Oracle's current free allowances. Registration normally requires a phone number and credit card, and availability is not guaranteed.


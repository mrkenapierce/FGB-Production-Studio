# FGB Production Studio

Desktop production studio for Football's Greatest Bears, Football's Greatest Bars, EPIC Communities, and future YouTube channels.

## Current Version

Version 2.6 with video-based and audio-first produced Shorts generation.

## Included Now

- Electron desktop shell
- FGB / FGBars / EPIC Communities / custom-channel profiles
- Countdown and production-screen tools
- Windows portable executable packaging
- Reusable one-word motion-caption renderer
- Video-based Produced Shorts Generator
- WAV-based Audio-First Shorts Generator
- Automatic or supplied time-coded transcription
- SRT, VTT, and timestamped TXT parsing
- Rule-based clip ranking with overlap and duplicate prevention
- Separate 1080 × 1920 MP4, JSON, TXT, and caption files
- GitHub Actions tests and rendering workflows

## Local Run

```bash
npm install
npm start
```

Open **Shorts Generator**, then choose either the video-based workflow or **Audio-First Shorts**.

## Video-Based Produced Shorts

Use this mode when the original source video is available.

1. Select the video file you own or are authorized to edit.
2. Select the episode's time-coded SRT, VTT, or timestamped TXT captions.
3. Enter the episode title, number, channel, and optional YouTube reference URL.
4. Choose an output folder and generate separate MP4 and metadata files.

The YouTube URL is retained as attribution and metadata. The studio does not function as a generic YouTube downloader.

```bash
npm run generate:shorts -- \
  --input production-inputs/episode-004.mp4 \
  --transcript production-inputs/episode-004.srt \
  --output-dir dist-assets/shorts/episode-004 \
  --episode-number 004 \
  --episode-title "Episode title" \
  --project fgb \
  --reference-url https://youtu.be/REFERENCE
```

## Audio-First Shorts

Use this mode when the WAV audio is available but the source video is not. The result is intentionally designed editorial content rather than a simulated excerpt from the missing video.

Default batch:

- Three premium slots
- Five rapid-output slots
- Automatic tactical treatment when narration discusses formations, routes, coverages, schemes, matchups, or related strategy

Premium slots use an animated sports/editorial newspaper treatment. A qualifying premium clip becomes a tactical diagram explainer. Rapid clips use clean quote-driven channel graphics.

### Audio intake

- WAV is the standard audio input.
- A time-coded SRT, VTT, or TXT transcript is optional.
- When no transcript is supplied, the studio converts the WAV to transcription-sized audio sections and requests word- and segment-level timestamps from the configured transcription service.
- An optional visual folder can contain AI-generated images, licensed stock visuals, public-domain material, or user-supplied photographs. File names are matched against clip subjects when possible.
- Without visual assets, the studio generates complete branded editorial graphics internally.

### Transcription configuration

The desktop interface can save an OpenAI API key using Electron's operating-system-backed secure storage. The key is not shown again and is passed only from the Electron main process to the transcription request. `OPENAI_API_KEY` can be used instead.

A supplied time-coded transcript bypasses external transcription entirely.

### Audio-first command line

```bash
npm run generate:audio-shorts -- \
  --audio production-inputs/episode-004.wav \
  --output-dir dist-assets/audio-shorts/episode-004 \
  --episode-number 004 \
  --episode-title "Episode title" \
  --project fgb \
  --reference-url https://youtu.be/REFERENCE \
  --api-key "$OPENAI_API_KEY"
```

Optional controls:

```text
--transcript episode-004.srt
--visual-assets-dir visual-assets/episode-004
--total-shorts 8
--premium-shorts 3
--channel-name "Future Channel"
--watermark CHANNEL
```

## Locked Output Protocol

Both Shorts modes produce:

- 1080 × 1920 portrait MP4
- Original source audio
- Exactly one caption word visible at a time
- Caption color `#C83803`
- Black outline and drop shadow
- Condensed bold italic sports typography
- Lower-middle safe-area placement
- Channel-specific watermark and metadata
- Separate MP4, JSON, TXT, and caption timing files
- Episode-level JSON and Markdown production records

## Tests

```bash
npm test
```

Tests cover timestamp and transcript parsing, candidate-window generation, overlap prevention, word-caption sequencing, transcription-chunk merging, premium/rapid tier assignment, and tactical-treatment selection.

## Windows EXE Build

```bash
npm run dist:win
```

The packaged application includes FFmpeg, the preload bridge, both Shorts generators, transcription controls, renderer pages, and production scripts.

The Windows workflow must remain at:

```text
.github/workflows/build-windows.yml
```

## Standalone One-Word Caption Rendering

```bash
npm run render:captions -- \
  --input production-inputs/FGBars_Episode_003_Production_Screen.mp4 \
  --captions captions/fgbars-003-word-demo.json \
  --output dist-assets/captions/FGBars_Episode_003_Word_Captions.mp4
```

The renderer validates that caption timings do not overlap and rejects multi-word caption entries by default.

## Production Direction

This repository is the canonical source-controlled production system. The earlier Lovable clip interface remains a planning prototype and is not the production renderer.

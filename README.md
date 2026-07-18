# FGB Production Studio

Desktop production studio for Football's Greatest Bears, Football's Greatest Bars, and EPIC Communities.

## Current Version

Version 2.5 foundation with produced-Shorts generation.

## Included Now

- Electron desktop shell
- FGB / FGBars / EPIC Communities project switcher
- Countdown screen
- Working preset files
- Visibility controls
- Community Partner fields
- EPIC Communities QR placeholder
- Windows packaging configuration
- Reusable one-word motion-caption renderer
- GitHub Actions caption-rendering workflow
- Produced Shorts Generator for separate 1080 × 1920 MP4 files
- SRT, VTT, and timestamped TXT transcript parsing
- Rule-based clip ranking with overlap and duplicate prevention
- Separate JSON, TXT, caption-timing, and episode-package files

## Local Run

Install Node.js LTS, then run:

```bash
npm install
npm start
```

In the desktop app, select **Shorts Generator**.

## Produced Shorts Generator

The generator converts a source episode into finished vertical Shorts. Its production path is:

1. Select the original video file you own or are authorized to edit.
2. Select the episode's time-coded captions as SRT, VTT, or timestamped TXT.
3. Enter the episode title, number, project, and optional YouTube reference URL.
4. Choose an output folder and the number of Shorts.
5. Generate separate MP4 and metadata files.

The YouTube URL is retained as source attribution and used in copy-ready metadata. The generator intentionally does not download arbitrary YouTube videos. For videos already published on your own channel, use the original upload file and export the captions from YouTube Studio.

Default output specifications:

- 1080 × 1920 portrait MP4
- Original audio retained
- Full-frame video over a blurred portrait background, or center-crop mode
- Exactly one caption word visible at a time
- Caption color `#C83803`
- Black outline and drop shadow
- Condensed bold italic sports font
- Lower-middle caption-safe placement
- FGB, FGBARS, or EPIC text watermark
- Five to ten ranked, non-overlapping candidate clips by default
- Typical clip duration: 20–58 seconds

Each Short is delivered separately with:

- `.mp4` produced video
- `.json` structured metadata
- `.txt` copy-ready title, description, hashtags, pinned comment, and source timestamp
- `.captions.json` word timings
- `.fffilter` reproducible FFmpeg filter instructions

The episode folder also receives a consolidated JSON and Markdown production record.

### Command-line generation

```bash
npm run generate:shorts -- \
  --input production-inputs/episode-004.mp4 \
  --transcript production-inputs/episode-004.srt \
  --output-dir dist-assets/shorts/episode-004 \
  --episode-number 004 \
  --episode-title "The Truth About Caleb Williams Nobody Wants To Admit" \
  --project fgb \
  --reference-url https://youtu.be/REFERENCE
```

Optional controls:

```text
--limit 8
--min-seconds 20
--max-seconds 58
--target-seconds 38
--layout blur|crop
--watermark FGB
--font /path/to/condensed-bold-font.ttf
--caption-color #C83803
```

### Tests

```bash
npm run test:shorts
```

The tests cover timestamp parsing, SRT/VTT parsing, coherent candidate-window generation, overlap prevention, and one-word caption sequencing.

## Windows EXE Build

The repository includes package support for:

```bash
npm run dist:win
```

The packaged application includes the Shorts generator, FFmpeg binary, desktop preload bridge, renderer, and production scripts.

The GitHub Actions workflow must be stored at:

```text
.github/workflows/build-windows.yml
```

A workflow file placed at the repository root will not run.

## One-Word Caption Rendering

The standalone caption renderer places exactly one word on screen at a time. The locked FGB/FGBars caption style uses:

- Caption color: `#C83803`
- Black outline
- Black drop shadow
- Condensed bold italic sports font
- Centered lower-screen placement
- 30 fps output
- One caption replacing the previous caption

The included Episode 003 demonstration preset is:

```text
captions/fgbars-003-word-demo.json
```

Render locally with:

```bash
npm run render:captions -- \
  --input production-inputs/FGBars_Episode_003_Production_Screen.mp4 \
  --captions captions/fgbars-003-word-demo.json \
  --output dist-assets/captions/FGBars_Episode_003_Word_Captions.mp4
```

Create a five-second review copy by adding:

```bash
--clip-duration 5
```

The renderer validates that caption timings do not overlap and, by default, rejects caption entries containing more than one word.

## GitHub Caption Workflow

Run the `Render Word Captions` workflow from the repository Actions tab. It accepts:

- A repository path to the source production-screen video
- A repository path to the caption JSON file
- The desired output filename
- An optional preview duration

The completed MP4 is uploaded as a downloadable GitHub Actions artifact.

## Production Direction

This repository replaces the earlier prototype ZIP workflow. Future work should happen here as source-controlled updates.

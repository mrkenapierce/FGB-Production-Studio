# FGB Production Studio

Desktop production studio for Football's Greatest Bears, Football's Greatest Bars, and EPIC Communities.

## Current Version

Version 2.5 foundation.

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

## Local Run

Install Node.js LTS, then run:

```bash
npm install
npm start
```

## Windows EXE Build

The repository includes package support for:

```bash
npm run dist:win
```

The GitHub Actions workflow must be stored at:

```text
.github/workflows/build-windows.yml
```

A workflow file placed at the repository root will not run.

## One-Word Caption Rendering

The caption renderer places exactly one word on screen at a time. The locked FGB/FGBars caption style uses:

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

This repo replaces the earlier prototype ZIP workflow. Future work should happen here as source-controlled updates.

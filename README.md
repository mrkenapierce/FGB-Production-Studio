# FGB Production Studio

Desktop production studio for Football's Greatest Bears, Football's Greatest Bars, and EPIC Communities.

## Current Version

Version 2.0 foundation.

## Included Now

- Electron desktop shell
- FGB / FGBars / EPIC Communities project switcher
- Countdown screen
- Working preset files
- Visibility controls
- Community Partner fields
- EPIC Communities QR placeholder
- Windows packaging configuration

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

## Production Direction

This repo replaces the earlier prototype ZIP workflow. Future work should happen here as source-controlled updates.

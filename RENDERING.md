# FGB Production Studio Automated Rendering

The long-term goal is to remove manual screen recording from the FGB workflow.

## Intended Workflow

1. Add episode information to `render-list.json`.
2. Run the automated renderer.
3. Download finished video files from the `renders` folder or GitHub Actions artifact.

## Render List Format

Each render item should look like this:

```json
{
  "project": "fgb",
  "episodeNumber": "022",
  "episodeTitle": "The Biggest Difference Between Good Teams And Great Teams",
  "durationSeconds": 900,
  "preset": "standard"
}
```

Supported project values:

- `fgb` — Football's Greatest Bears
- `fgbars` — Football's Greatest Bars
- `epic` — EPIC Communities

Supported preset values:

- `standard`
- `minimal`
- `partner`
- `sponsor`
- `countdown`
- `full`

## Best Final System

The best version of this system is a batch renderer that reads `render-list.json` and automatically creates countdown videos without requiring manual screen recording.

The renderer should:

- load each title and episode number
- apply the selected project branding
- keep the QR in the lower-right safe zone
- keep the timer in the center safe zone
- render the countdown automatically
- export each episode as a finished video file

## Practical Note

A browser-only file can record WebM, but true MP4 rendering requires a desktop build or an automated render process using FFmpeg.

For production, the preferred output is MP4.

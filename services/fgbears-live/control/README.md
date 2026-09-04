# ChatGPT → GitHub → Oracle Live Broadcast Control

This directory defines the versioned control contract for dynamic visual programming on the FGB live stream.

## Safety boundary

- The existing `fgbears-live.service` remains untouched by this control package.
- Nothing in this directory deploys automatically to the Oracle VM.
- Production activation requires an explicit deployment step after validation and testing.
- GitHub is the source of truth for schedules and text-based creatives.
- Oracle remains the playout authority.

## Operating model

1. The operator tells ChatGPT what to add, change, pause, or remove.
2. ChatGPT creates or edits a text-based creative (SVG) and updates `schedule.json`.
3. GitHub Actions validates the schedule and creative references.
4. After explicit production authorization, Oracle syncs the approved control package.
5. Oracle renders/normalizes creatives locally, caches the schedule, and feeds the playout controller.

## Initial content types

- `ad`
- `trivia_question`
- `trivia_reveal`
- `giveaway`
- `house`
- `live_message`
- `fallback`

## Schedule contract

`schedule.json` is intentionally simple. Each item contains:

- `id`: unique identifier
- `type`: supported content type
- `asset`: repository-relative creative path
- `duration_seconds`: display duration
- `frequency_per_hour`: optional frequency target
- `start_at`: optional ISO-8601 timestamp
- `end_at`: optional ISO-8601 timestamp
- `priority`: integer, higher wins
- `active`: boolean

The Oracle side must always retain cached house/fallback programming so a control-plane outage cannot blank the stream.

## Creative format

Version 1 uses SVG as the canonical text-based creative because ChatGPT can create and update it directly in GitHub. Oracle converts approved SVG files to broadcast-ready raster/video assets locally before playout.

## Production status

This package is scaffolding only until the playout proof of concept is certified. Do not wire it into the running `fgbears-live.service` without separate authorization.

# CNT daily episode title convention

**Status:** Approved publishing requirement; automation integration not yet verified.
**Scope:** Cruise News & Trivia (CNT) daily recorded news episodes only. Do not change CNT trivia livestream titles, FGB, or FGBars.

## Required title

`Today's Cruise News: Month Day, Year`

For an episode published on October 26, 2026, the exact title is:

`Today's Cruise News: October 26, 2026`

## Publisher integration contract

1. Generate the title **at the actual publication step**, not while drafting, rendering, uploading, or scheduling. If publishing is scheduled for a later date, format the date for the scheduled publication instant (or re-resolve just before the publish API call).
2. Convert the actual publication instant to `America/Chicago` before formatting. This accounts for both Central Daylight and Central Standard Time. Do not use a UTC date or an unchecked server-local date.
3. Use English full month names, a numeric day without a leading zero, a comma and a four-digit year.
4. Match the literal prefix `Today's Cruise News: `; do not append episode numbers, default suffixes, or extra text.
5. Keep manual retitles possible; do not run a recurring process that overwrites titles of already published videos.
6. Apply only to CNT's daily news uploads; no change to existing video titles unless separately authorized.
7. Make publication idempotent: retries for the same published episode should preserve the intended published-date title and should not create a duplicate upload.

JavaScript example for a publishing process, where `publishTime` is the actual (or scheduled) publication instant:

```js
const dateLabel = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  month: 'long',
  day: 'numeric',
  year: 'numeric',
}).format(new Date(publishTime));
const title = `Today's Cruise News: ${dateLabel}`;
```

## Checks before enabling

- 2026-10-26 18:00 Central -> `Today's Cruise News: October 26, 2026`
- Crossing midnight UTC but not midnight Central must not change the Central date.
- Daylight saving time boundaries must retain the correct Central calendar date.
- CNT livestream metadata, FGB daily episodes and FGBars uploads remain unaffected.

## Deployment status

The connected `mrkenapierce/FGB-Production-Studio` repository contains CNT livestream diagnostics, but no verified CNT daily-news YouTube upload/publish job was located as of 2026-10-26. This document is an authoritative production naming requirement only; it does **not** itself change live YouTube publishing behavior. Wire the above formatting to the actual CNT daily episode publisher once its source is accessible, then verify a real publish.

// Existing GitHub workflow entry point.
// Delegates to the standardized FGB / FGBars production package renderer.
// Current production target: FGBars Episode 005.
process.env.EPISODE_FILTER = '005';
process.env.COUNTDOWN_ZERO_HOLD_SECONDS = '1';
await import('./render-standard-production-package.mjs');

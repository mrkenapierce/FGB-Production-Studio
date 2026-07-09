// Existing GitHub workflow entry point.
// Delegates to the production package renderer.
// Current production target: FGB Episode 025.
process.env.EPISODE_FILTER = '025';
process.env.COUNTDOWN_ZERO_HOLD_SECONDS = '1';
await import('./render-production-package.mjs');

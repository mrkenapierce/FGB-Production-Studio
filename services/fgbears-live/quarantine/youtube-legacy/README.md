# Quarantined legacy YouTube pathways

This directory preserves retired FGBears YouTube implementations for audit/history only.

## Sole authorized live path

`services/fgbears-live/youtube-v2/`

The shared master is rendered once. Rumble receives the shared program by copy-remux.
Only the existing YouTube v2 destination applies a Lovable-selected difference layer.

## Quarantine rules

- Files in this directory are non-executable.
- Nothing here may be installed into `/opt/fgbears-live/bin` or `/usr/local/bin`.
- Retired systemd units remain masked in production.
- Retired router, freeze-box, off-host compositor, old relay, trivia-overlay, and audio-watchdog paths must not be reactivated.
- Historical code must be rebuilt against the v2 architecture if functionality is ever needed again; it must not be copied back as a patch.

Production verification is performed by `youtube-v2/verify-youtube-v2.sh`.

# YouTube routing quarantine

Status: RETIRED / DO NOT EXECUTE

Effective September 3, 2026, the FGB production system no longer routes the live program to YouTube.

Authoritative production posture:
- Rumble remains the live video destination.
- Lovable `youtube_enabled` is false.
- Lovable `route_redirect_cta` is off.
- The YouTube-only trivia redirect overlay is disabled.
- All dedicated YouTube deployment, recovery, maintenance, credential-discovery, probe, validation, and broadcast GitHub Actions previously under `.github/workflows/` have been moved into this quarantine directory with `.disabled` suffixes so GitHub Actions cannot execute them.

These files are retained only for audit/history and must not be moved back into `.github/workflows/` without an explicit future reauthorization and a fresh architecture review.

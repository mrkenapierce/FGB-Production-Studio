# CNT storage repair — October 28, 2026

Verified 4:27 p.m. America/Chicago. User authorized cleanup, structural repair, and clearing today's two episodes if unrecoverable.

Cause: installed receipt-gated cleanup expected daily/published segment receipts for raw ten-minute rolling chunks, retaining 210 files indefinitely. CNT rolling storage reached about 47 GiB; recorder entered low-disk protection around 11:01 a.m. Central.

Installed CNT-specific cnt-buffer-cleanup.py via systemd override. Every five minutes it requires a fresh complete remote episode dependency snapshot, unions durable pending dependencies and fresh daily/episode holds, preserves newest/changed files and three hours of recent footage, and removes only older unneeded regular TS files after inspecting duration. Uses ffprobe in existing CNT worker container. Errors fail closed. FGB cleanup and both capture containers unchanged.

Verified cleanup: 202 files, 48,114,930,576 bytes removed; 8 protected. Free disk 55,000 MiB; df reports 54 GiB free / 25% used. New recording live-20261028-162638--0500.ts observed at 25,427,968 bytes. Low disk marker cleared. Timer active. Safety tests passed.

Evidence: https://github.com/mrkenapierce/FGB-Production-Studio/actions/runs/40771915542

Today's failed episodes had no YouTube video IDs and error 'no local recording covers the aired window'. Owner-requested clearing implemented as enabled=false, retaining failure history and source audio:
- 5bd1bf19-f79b-4221-a4c2-2ceb5f3b8fac — Virgin Voyages: Marketing vs. Reality — Is It Worth the Hype?
- 373b8881-20dd-4e7d-8585-825e2e6ca595 — Are Cruise Ships Truly Autism-Friendly? What Families Need to Know

Read-back verified both disabled. No published videos deleted. Missing footage cannot be recovered from local archive; new airing would require a separate decision.

Ideas / end-of-day report: retain dependency-aware cleanup; distinguish raw buffer from published archives; surface recorder low-disk stoppages alongside stream health. No new future automation created.

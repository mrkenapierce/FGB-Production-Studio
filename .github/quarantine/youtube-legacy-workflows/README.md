# Quarantined legacy YouTube workflows

Files here were moved out of `.github/workflows`, which deactivates them as GitHub Actions.

They represent superseded relay, router, freeze-box, partial/off-host compositor, fixed-card,
legacy routing-consumer, legacy ingest/failure diagnostics, and related cutover/restore pathways.

The only production deployment workflow for destination-specific YouTube presentation is:

`../../workflows/youtube-v2-deploy.yml`

The only validation workflow for that path is:

`../../workflows/youtube-v2-validate.yml`

Do not move a quarantined workflow back into `.github/workflows`. If a capability is
needed again, rebuild it against the sole YouTube v2 architecture.

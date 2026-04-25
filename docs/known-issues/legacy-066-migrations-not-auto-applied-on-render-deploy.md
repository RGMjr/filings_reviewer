---
autonomy: review
discovered: '2026-04-21'
estimated: S
id: 66
note: Wire apply_migrations into Render deploy; infra-change risk
severity: medium
slug: migrations-not-auto-applied-on-render-deploy
source: legacy
status: open
title: Migrations Not Auto-Applied on Render Deploy
touches:
- render.yaml
- .claude/rules/infrastructure.md
updated: '2026-04-24'
---

### Problem

`scripts/apply_migrations.py` is idempotent (via the `schema_migrations` ledger) and keeps a registered list through `sql/39_v2_ingest_batches.sql`, but Render's blueprint-driven deploys do not invoke it. When PR #48 merged with `sql/39_v2_ingest_batches.sql`, Render auto-deployed `filings-onboarding-runner` without running the migration, and the worker then crashed every ~5 minutes with `psycopg.errors.UndefinedTable: relation "v2_ingest_batches" does not exist` until an operator manually ran `python3 scripts/apply_migrations.py` against Neon. Every future schema-change PR has the same failure mode.

### Next Steps

- Add a Render pre-deploy command on `filings-reviewer` (the web service with the longest deploy budget) that runs `python3 scripts/apply_migrations.py` before the container starts. The ledger makes it safe on every deploy.
- Alternative: a dedicated one-shot Render Job that runs the migration runner on every merge to main, blocking service redeploys until it exits 0.
- Document the chosen path in `.claude/rules/infrastructure.md` so future schema-change PRs don't repeat this.

### Cross-References

- `scripts/apply_migrations.py` — migration runner (idempotent via `schema_migrations` ledger)
- `sql/39_v2_ingest_batches.sql` — the migration that triggered this discovery
- `render.yaml` — pre-deploy hook would attach to the web service entry

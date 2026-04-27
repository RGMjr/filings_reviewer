---
autonomy: n/a
discovered: '2026-04-21'
estimated: S
id: 66
note: Wire apply_migrations into Render deploy; infra-change risk
pr_refs:
- 199
severity: medium
slug: migrations-not-auto-applied-on-render-deploy
source: legacy
status: resolved
title: Migrations Not Auto-Applied on Render Deploy
touches:
- render.yaml
- .claude/rules/infrastructure.md
updated: '2026-04-27'
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

### Resolution

This fragment is a stale duplicate of legacy-095. The fix it requested — wiring `python3 scripts/apply_migrations.py` as a Render pre-deploy command on the `filings-reviewer` service — was shipped in PR #199 (commit `eed95a8`, `fix(deploy): auto-apply schema migrations on every Render deploy via preDeployCommand`). `render.yaml` line 36 now reads `preDeployCommand: python3 scripts/apply_migrations.py` under the `filings-reviewer` web service entry, exactly as this fragment required. The residual checksum-guard relaxation (comment-only diffs no longer force ledger reconciliation) was finished by PR #243, tracked under legacy-095, which is itself closed as resolved. No further action is needed here.

---
autonomy: review
discovered: '2026-04-23'
estimated: M
id: 95
severity: high
slug: migrations-drift-from-prod-no-post-deploy-apply
source: legacy
status: open
title: Schema Migrations Drift From Prod — No Post-Deploy Apply Step
touches:
  - scripts/apply_migrations.py
  - render.yaml
  - src/web/app.py
  - sql/
updated: '2026-04-23'
---

### Problem

Code that references new schema can ship to prod (Render) without the
corresponding SQL migration being applied. Nothing in the deploy path
runs `scripts/apply_migrations.py` against Neon after a merge to `main`.
The result is runtime `UndefinedColumn` / `UndefinedTable` errors in
prod while the same queries succeed in local dev and CI (both of which
apply migrations implicitly via pytest/Docker bootstrap).

**Trigger case (2026-04-23):** PR #151 merged with `sql/42_add_detected_metrics_to_v2_image_assets.sql` and `sql/43_create_v2_image_metric_confirmations.sql`. Code at `src/infra/db.py:1709` began selecting `v.detected_metrics` from `v2_image_assets`. Neon never received the migrations. Every call to `get_image_review_candidates_for_filing_v2()` — which `review_filing` invokes unconditionally for the Images-tab counts — raised `psycopg.errors.UndefinedColumn`, got caught by the try/except at `src/web/routes/review_unified.py:472-475`, flashed "Error loading review", and redirected to the filing list. Users saw "Review button flashes and returns to the list." Auto-accepted facts were effectively unreviewable.

Fix was a one-shot manual `python3 scripts/apply_migrations.py` against `$DATABASE_URL`. Both migrations applied cleanly. Review page recovered on next request.

### Compounding issue: checksum-guard false positive

During the manual fix the runner halted on `37_create_analytics_role.sql` with
```
HALTED: Checksum mismatch for 37_create_analytics_role.sql: expected e7b06ff3…, got a589d96a…
```
Commit `8d09001` (#111) added a purely cosmetic `-- cluster-ddl-ok: ...` comment to `sql/37_create_analytics_role.sql` to silence the cluster-DDL pre-commit guard. No DDL change, no DB impact — but the content hash changed, so the ledger's SHA-256 check flagged drift and refused to proceed. Had to reconcile the ledger row manually:
```sql
UPDATE schema_migrations SET checksum = '<new_hash>' WHERE id = '37_create_analytics_role.sql';
```
Any future comment-only edit to an applied migration file will trip the same guard and block all subsequent applies — including emergency ones. This has happened before (see legacy-018, legacy-090).

### Blast radius

- Prod features silently break on any PR that adds a migration.
- The failure surfaces only when a specific endpoint queries the new column/table — often hours or days after deploy, not at build/health-check time.
- `scripts/apply_migrations.py` is the only recovery path, and the checksum guard can block even that.
- No alerting: Render logs show per-request exceptions but nothing watches the rate.

### Next steps

Pick one (or more) of:

1. **Render post-deploy hook.** Add to `render.yaml` under the `filings-reviewer` service:
   ```yaml
   preDeployCommand: python3 scripts/apply_migrations.py
   ```
   Runs after build, before traffic cuts over. Blocks deploy if migrations fail. This is the minimum viable fix.

2. **App-startup migration check.** In `src/web/app.py::create_app`, after pool init, SELECT `MAX(id)` from `schema_migrations` and compare against a pinned "expected head" constant maintained in `scripts/apply_migrations.py::MIGRATIONS[-1]`. Fail-fast with a clear error if behind. Catches the "migration not applied" case even when the pre-deploy hook is skipped (e.g., manual restart).

3. **Relax the checksum guard for comment-only diffs.** In `scripts/apply_migrations.py::_checksum`, strip SQL comments (lines matching `^\s*--`) before hashing. Commit-marker comments (`-- cluster-ddl-ok:`) and operator-note comments should not force a ledger reconciliation. Alternatively: add a `--reconcile-ledger` flag that updates the stored checksum to the file's current hash when the diff is comment-only, without re-executing the migration.

4. **CI schema-drift check.** After apply-migrations in the integration-tests job, diff the applied set against `MIGRATIONS` and fail if any file in `sql/` is not registered. Catches the "developer added sql/42 but forgot to register it" case that's worse than this one.

5. **Alerting.** Simple: log an ERROR line with a stable token (e.g., `MIGRATION_DRIFT_DETECTED`) whenever the app-startup check in #2 fires, and add a Render log alert on that string. No new infra.

**Recommended order:** #1 (render.yaml pre-deploy) + #3 (relax checksum) as the tight Phase-1 pair — unblocks routine deploys and prevents the guard from re-blocking future emergency applies. #2 and #4 as Phase-2 defense-in-depth.

### Verification after fix

- Trigger a no-op deploy on Render and confirm `scripts/apply_migrations.py` runs in the pre-deploy log.
- Temporarily roll back a migration's ledger entry (`DELETE FROM schema_migrations WHERE id='42_*'`) and confirm the next deploy re-applies it.
- Add a comment-only change to an applied migration, commit, push, and confirm the pre-deploy hook does not halt.
- Tail `filings-reviewer` Render logs for 15 minutes post-deploy: zero `UndefinedColumn` / `UndefinedTable` exceptions.

### Related history

- **legacy-018** — checksum mismatch on `sql/01_create_schema.sql`; self-healed via V1 retirement. Same class of problem.
- **legacy-090** — integration tests fail on sql/37 checksum. Same class of problem.
- Commit `8d09001` (#111) — added the cluster-DDL pre-commit guard and the `-- cluster-ddl-ok:` marker that caused this round's checksum drift.
- PR #151 — shipped `v.detected_metrics` SELECT without enforcing migration apply; the trigger case for this issue.

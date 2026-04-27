---
autonomy: review
discovered: '2026-04-27'
estimated: M
id: 110
pr_refs: []
severity: medium
slug: migration-registry-drift-between-apply-scripts
source: legacy
status: open
title: Migration registry drift between apply_migrations.py and apply_all_migrations.py
touches:
  - scripts/apply_migrations.py
  - scripts/apply_all_migrations.py
  - render.yaml
  - .claude/rules/sql.md
updated: '2026-04-27'
---

### Problem

`scripts/apply_migrations.py::MIGRATIONS` and `scripts/apply_all_migrations.py::MIGRATION_ORDER` are two parallel hand-curated lists of SQL migration files that must stay in sync, with no tooling to enforce equality. They currently diverge.

**Surfaced by:** Codex review on PR #197, then verified by direct comparison on `main` (2026-04-25).

### Divergence (as of 2026-04-25)

`apply_migrations.py::MIGRATIONS` is missing five migrations that `apply_all_migrations.py::MIGRATION_ORDER` runs:

| Migration | Comment in apply_migrations.py |
|---|---|
| `26_drop_filing_metric_incidence.sql` | (no comment — silently absent) |
| `27_drop_v1_metric_tables.sql` | (no comment — silently absent) |
| `33_fix_identity_index.sql` | "applied to Neon out-of-band" (intentional) |
| `41_normalize_accession_numbers.sql` | (no comment — silently absent) |
| `46_extend_audit_http_method_constraint.sql` | (no comment — silently absent) |

There is also a 04-prefix ordering disagreement:
- apply_migrations.py: `04_add_post_combination → 05_* → 03_create_analysis_schema → 04_seed_metrics_taxonomy`
- apply_all_migrations.py: `03_* → 04_add_post_combination → 04_seed_metrics_taxonomy → 05_*` (alpha-sort)

### Production state (verified 2026-04-25 via Neon `schema_migrations` ledger)

All 54 migrations are applied to prod, including the 5 "missing" from `apply_migrations.py`. The drift is forward-looking only — a fresh-from-scratch deploy that runs `apply_migrations.py` against a virgin DB would skip them. No current service is at risk because they are already applied.

The 04-prefix anomaly is also moot in prod: prod's `applied_at` timestamps show the files were applied in a single batch on 2026-03-13 and the resulting schema is stable.

### Open question (must be answered before fixing)

**Which apply script does Render actually run?** PR #199 (`fix(deploy): auto-apply schema migrations on every Render deploy`) merged 2026-04-25 01:30, and migrations 41 and 46 appeared in the prod ledger at 01:22 the same day — *before* PR #199's merge. Yet `render.yaml` audit on 2026-04-25 found no `preDeployCommand` for any service. Either:

1. PR #199 wired migration application via a Docker entrypoint or service-startup script (not `preDeployCommand`), or
2. The 41/46 application predates PR #199 and was triggered by some other mechanism (manual `psql`, prior `apply_all_migrations.py` run, Docker image init).

Until this is traced, we don't know which list (`MIGRATIONS` or `MIGRATION_ORDER`) is the canonical production path. Changing deploy tooling without that answer is the kind of silent regression that only surfaces on the next clean-DB bootstrap.

### Recommended resolution (deferred)

Single source of truth in `src/infra/migrations.py`:

```python
SQL_DIR = ROOT / "sql"
KNOWN_SKIPS = frozenset({"00_init_databases.sql"})  # Docker init only — requires superuser

def migration_files() -> list[str]:
    return sorted(p.name for p in SQL_DIR.glob("*.sql") if p.name not in KNOWN_SKIPS)
```

Both apply scripts import and use this. The new alpha-sorted order matches `apply_all_migrations.py::MIGRATION_ORDER`, which is exercised on every CI integration test against a fresh DB — so the order is safe-by-induction.

### Pre-implementation gate (must complete before consolidating)

1. Trace what PR #199 actually wired — read the PR diff in detail and confirm whether `apply_migrations.py` or `apply_all_migrations.py` is the production deploy entrypoint.
2. If both are reachable in different paths, decide which one should be canonical.
3. Read each migration's DDL to confirm the new alpha-sorted order has no hidden ordering dependencies (the 04-prefix anomaly is the most suspicious — confirm 03/04/05 don't have cross-references).
4. Add an integration test that asserts `migration_files()` produces a list that applies cleanly on a fresh DB.
5. Update `.claude/rules/sql.md` to point at the single source of truth and remove references to either literal list.

### Why not fix now

- No prod gap exists — only forward-looking risk.
- The PR-review audit (2026-04-25) that surfaced this had four other improvements that were ship-ready and shipped (PRs #217–#220). PR 4 expanded into deploy-tooling investigation that needs a deliberate, traced approach rather than a same-day ship.
- The 04-prefix ordering question deserves migration-by-migration DDL review, not a glob-and-trust shortcut.

### Cross-references

- PR-review audit plan: `~/.claude/plans/can-you-read-through-stateless-popcorn.md` (PR 4 / Group C2)
- Codex P1 finding: PR #197 review comments
- Related: legacy-085 `apply-all-migrations-stale-at-40` (older sibling — may already capture some of this)
- Related: legacy-088 `migration-order-drift-no-precommit-guard`

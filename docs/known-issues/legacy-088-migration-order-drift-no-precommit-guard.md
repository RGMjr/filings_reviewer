---
id: 88
source: legacy
slug: migration-order-drift-no-precommit-guard
title: No pre-commit guard catches sql/ files missing from MIGRATION_ORDER
status: resolved
severity: medium
autonomy: skip
estimated: S
touches:
  - scripts/apply_all_migrations.py
  - .pre-commit-config.yaml
discovered: '2026-04-23'
updated: '2026-04-23'
pr_refs: []
note: Add a pre-commit hook that fails if any sql/NN_*.sql on disk lacks an entry in MIGRATION_ORDER or EXCLUDED_FILES.
---

### Problem

`scripts/apply_all_migrations.py` has drifted twice (issues #46 and #85) because new SQL migration files land on disk without a corresponding entry in `MIGRATION_ORDER`. The `check_unregistered_migrations` guard only fires at runtime (`--dry-run`), not at commit time, so the drift isn't caught until someone runs the script.

### Next Steps

- Add a pre-commit hook (or `local` hook in `.pre-commit-config.yaml`) that runs `python3 scripts/apply_all_migrations.py --dry-run` (which exits 1 when unregistered files are found) before each commit.
- Alternatively, write a small standalone check script and register it as a `local` repo hook so it doesn't require a DB connection.
- Verify the hook runs in CI as well (the pre-commit framework is already in use for ruff and the extraction guard).

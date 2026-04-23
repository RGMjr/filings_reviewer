---
autonomy: safe
discovered: '2026-04-22'
estimated: XS
id: 85
note: Recurrence of Issue #46. Append `40_full_page_scan_and_ocr_provenance.sql` to `MIGRATION_ORDER`.
severity: medium
slug: apply-all-migrations-stale-at-40
source: legacy
status: resolved
title: '`scripts/apply_all_migrations.py` MIGRATION_ORDER missing migration 40'
touches:
  - scripts/apply_all_migrations.py
updated: '2026-04-22'
---

### Problem

`scripts/apply_all_migrations.py` `MIGRATION_ORDER` ends at `39_v2_ingest_batches.sql`, but `sql/40_full_page_scan_and_ocr_provenance.sql` has existed on disk since before 2026-04-22. On a fresh-DB setup, running the script will skip migration 40 entirely. The `check_unregistered_migrations` guard flags this at `--dry-run` time but the list itself is stale.

This is a recurrence of Issue #46 (resolved 2026-04-20 by extending the list through `38_create_analytics_views.sql`) — the drift pattern resurfaced as soon as new migrations landed. A related fragment (#85) covers migration 41 of the same commit, which was registered correctly in this PR; #40 was left alone to keep scope narrow.

### Next Steps

- Append `"40_full_page_scan_and_ocr_provenance.sql"` to `MIGRATION_ORDER` in `scripts/apply_all_migrations.py`.
- Confirm the migration itself is idempotent (it uses `ALTER TABLE ... DROP CONSTRAINT IF EXISTS` / `ADD COLUMN IF NOT EXISTS`, so re-running on a DB where it was already applied manually should be safe, but verify before registering).
- Consider a pre-commit hook that fails if any `sql/NN_*.sql` file is on disk without a matching entry in `MIGRATION_ORDER` or `EXCLUDED_FILES`. That would close the drift class, not just this one recurrence.

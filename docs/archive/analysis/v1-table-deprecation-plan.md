# V1 Table Deprecation — Completion Record

V1 retirement is complete as of 2026-04-18. This document now serves as a historical record of which tables were dropped, when, and by which migration.

## Dropped Tables

**`filing_metric_incidence`** — V2 persistence formerly wrote to this V1 table "for analytics compatibility." No codebase readers were found. `V2PersistenceAdapter.persist_quality_scores()` converted to no-op stub (2026-04-17); table dropped by `sql/26_drop_filing_metric_incidence.sql` (applied 2026-04-18).

**`metric_values`** — V1 extraction result storage. All consumers migrated to `v2_metric_facts`. Dropped by `sql/27_drop_v1_metric_tables.sql` (applied 2026-04-18).

**`metric_definitions` (V1)** — V1 per-filing extracted definitions. Consumers migrated to `v2_metric_definitions` / `metrics`. Dropped by `sql/27_drop_v1_metric_tables.sql` (applied 2026-04-18).

**`image_review_candidates` / `image_review_decisions`** — V1 image review tables. Replaced by `v2_image_assets` (review columns added in `sql/28`) and new `v2_image_review_decisions` (`sql/29`). Unified review UI (`src/web/routes/review_unified.py`) reads V2 directly. Dropped by `sql/30_drop_v1_image_review.sql` (2026-04-17). Backfill tool: `scripts/migrate_image_decisions_to_v2.py` (idempotent; run before applying sql/30 in production).

**`review_candidates` / `review_decisions` / `suppressed_candidates` / `review_audit_log` / `learned_patterns` / `source_segments`** — V1 human-review pipeline tables, dropped 2026-04-18 by `sql/31_drop_v1_review_tables.sql` together with the V1 review modules, V1 API blueprint, and the `fresh_extractor` gold-standard path. Audit logging for V2 review routes now writes to `v2_audit_log` (created in the same migration; schema mirrors `review_audit_log` minus the `candidate_id` FK). See commit `refactor(v1): retire review_candidates + source_segments + suppressed_candidates` for the code-side changes.

## Production Deployment Note

Migration 31 must be applied manually against the production database after the code deploy has been live for at least one deploy cycle (so stale requests cannot hit deleted db.py methods). Before running:

```bash
pg_dump "$DATABASE_URL" -t review_decisions --data-only --column-inserts \
  > data/archive/review_decisions_pre_drop_2026-04-18.sql
pg_dump "$DATABASE_URL" -t review_candidates --data-only --column-inserts \
  > data/archive/review_candidates_pre_drop_2026-04-18.sql
```

Apply via `scripts/apply_all_migrations.py` on staging first, then manual `psql -f sql/31_drop_v1_review_tables.sql` on production.

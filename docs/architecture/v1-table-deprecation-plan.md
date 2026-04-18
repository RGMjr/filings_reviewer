# V1 Table Deprecation Plan

As of 2026-04-08, V2 is the production extraction pipeline. This document tracks the remaining V1 database tables, their current consumers, and the migration work needed to eventually drop them.

## Already Removed

**`filing_metric_incidence` (cross-write)** — V2 persistence layer formerly wrote to this V1 table "for analytics compatibility." Zero codebase readers were found (no `db.py` queries, no web routes, no scripts). `V2PersistenceAdapter.persist_quality_scores()` converted to no-op stub 2026-04-17; table dropped by `sql/26_drop_filing_metric_incidence.sql` (applied to live DB 2026-04-18).

**`metric_values`** — V1 extraction result storage. All consumers migrated to `v2_metric_facts`. Dropped by `sql/27_drop_v1_metric_tables.sql` (applied 2026-04-18).

**`metric_definitions` (V1)** — V1 per-filing extracted definitions. All consumers migrated to `v2_metric_definitions` or `metrics`. Dropped by `sql/27_drop_v1_metric_tables.sql` (applied 2026-04-18).

**`image_review_candidates` / `image_review_decisions`** — V1 image review tables. Replaced by `v2_image_assets` (review columns added in `sql/28`) and new `v2_image_review_decisions` (`sql/29`). Unified review UI (`src/web/routes/review_unified.py`) reads V2 directly; the `bridge_v2_images_to_review_candidates` db method and V1 routes/templates were retired. Dropped by `sql/30_drop_v1_image_review.sql` (2026-04-17). Backfill tool: `scripts/migrate_image_decisions_to_v2.py` (idempotent, run before applying sql/30 in production).

## Remaining V1 Tables

### `review_candidates` — HIGH difficulty

**Consumers:**
- `src/infra/db.py` — ~40 references (full CRUD: INSERT, SELECT, UPDATE)
- `src/web/routes/review.py` — nav routes (`next_candidate`, `jump_to_candidate`)
- `src/review/helpers.py` — reads/writes candidates
- `src/review/candidate_generator.py` — generates and inserts candidates
- `src/review/pattern_analyzer.py` — direct SQL queries
- 15+ scripts under `scripts/`

**Migration path:** Requires a dedicated project. The V1 review workflow (candidate generation → human review → decision) is still functional and produces data used for gold standard labeling. Migrating requires a V2-native review table, updating all 40+ `db.py` methods, migrating the web review UI, and updating all scripts. Estimated 2–4 weeks.

---

### `source_segments` — MEDIUM difficulty

**Consumers:**
- `src/infra/db.py` — `get_source_segments_for_filing()` (3 queries)
- `src/review/helpers.py` — calls `get_source_segments_for_filing()`
- `src/web/routes/review.py` — LEFT JOIN in V1 candidate data fetch

**Migration path:** V2 has `v2_segments` (stored as `Segment` in pipeline context but not always persisted). Migration requires ensuring V2 segment data is persisted and accessible at review time, then updating db.py queries.

---

### `suppressed_candidates` — LOW-MEDIUM difficulty

**Consumers:**
- `src/infra/db.py` — INSERT-only (suppression logging via `_bulk_log_suppressed`)
- `src/review/helpers.py` — suppression writes (invokes `bulk_insert_review_candidates(log_suppressed=True)`)

**Note:** All writes are triggered by V1 candidate generation. Deferred to the `review_candidates` migration — migrating this table in isolation would create an empty replacement with no meaningful writer.

**Migration path (deferred):** Create `v2_suppressed_facts` table keyed on V2 fact IDs; update `db.py:_bulk_log_suppressed` and `helpers.py`. Do alongside `review_candidates` migration.

---

## Recommended Sequence

1. Migrate `suppressed_candidates` → `v2_suppressed_facts`
2. Migrate `source_segments` (coordinate with review_candidates migration)
3. Migrate `review_candidates` — largest effort, own design document required

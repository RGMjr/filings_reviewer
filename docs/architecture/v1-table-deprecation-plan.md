# V1 Table Deprecation Plan

As of 2026-04-08, V2 is the production extraction pipeline. This document tracks the remaining V1 database tables, their current consumers, and the migration work needed to eventually drop them.

## Already Removed

**`filing_metric_incidence` (cross-write)** — V2 persistence layer formerly wrote to this V1 table "for analytics compatibility." Zero codebase readers were found (no `db.py` queries, no web routes, no scripts). The write was removed 2026-04-16; `V2PersistenceAdapter.persist_quality_scores()` is now a no-op stub.

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
- `src/gold_standard/fresh_extractor.py` — indirectly (HTMLSegmenter writes to this via persistence)

**Migration path:** V2 has `v2_segments` (stored as `Segment` in pipeline context but not always persisted). Migration requires ensuring V2 segment data is persisted and accessible at review time, then updating db.py queries.

---

### `image_review_candidates` — MEDIUM difficulty

**Consumers:**
- `src/infra/db.py` — `get_image_review_candidates_for_filing()`, `bridge_v2_images_to_review_candidates()`
- `src/web/routes/review_unified.py` — lines 341, 348 (the **V2 unified review UI** reads this table for the image review tab)

**Note:** This is the highest-priority migration because it blocks removal of the last V1 table reference from the V2 review UI. Migration requires a V2-native image review table and updating `review_unified.py`.

---

### `suppressed_candidates` — LOW-MEDIUM difficulty

**Consumers:**
- `src/infra/db.py` — INSERT-only (suppression logging)
- `src/review/helpers.py` — suppression writes

**Migration path:** Straightforward — create `v2_suppressed_facts` table, update the 2–3 db.py methods, update helpers.

---

### `metric_values` — LOW-MEDIUM difficulty

**Consumers:**
- `scripts/export_for_evaluation.py` — lines 66, 87, 336 (queries `metric_values` directly)
- `scripts/convert_v2_to_gold_standard.py` — line 233 (reads `metric_definitions` for metric descriptions; indirectly depends on this table remaining present)

**Note:** `src/extraction/` has been deleted from disk; any prior docstring reference there no longer exists.

**Action:** Before dropping, update `scripts/export_for_evaluation.py` to remove or replace V1 table queries. See Recommended Sequence note below.

---

### `metric_definitions` (V1) — LOW-MEDIUM difficulty

**Consumers:**
- `scripts/export_for_evaluation.py` — lines 66, 87, 336 (queries `metric_definitions`)
- `scripts/convert_v2_to_gold_standard.py` — line 233 (reads `metric_definitions` for metric descriptions)

**Note:** The V2 pipeline writes to `v2_metric_definitions` (a separate table). `src/extraction/` has been deleted from disk; any prior docstring reference there no longer exists.

**Action:** Before dropping, update `scripts/export_for_evaluation.py` and `scripts/convert_v2_to_gold_standard.py` to remove or replace V1 table queries.

---

## Recommended Sequence

1. **Prerequisite for `metric_values` / `metric_definitions`**: Update `scripts/export_for_evaluation.py` (lines 66, 87, 336) and `scripts/convert_v2_to_gold_standard.py` (line 233) to remove or replace all queries against these V1 tables (Option A from the remediation plan). Only after those scripts are updated can the tables be safely dropped.
2. Drop `metric_values` and `metric_definitions` (after step 1 is complete)
3. Migrate `suppressed_candidates` → `v2_suppressed_facts`
4. Migrate `image_review_candidates` → V2-native image review table (unblocks V2 UI cleanup)
5. Migrate `source_segments` (coordinate with review_candidates migration)
6. Migrate `review_candidates` — largest effort, own design document required

---
autonomy: n/a
discovered: '2026-04-18'
estimated: M
id: 24
note: 'Resolved 2026-04-28 as fragment-only closure: dev (Neon prod) and local
  Docker test DB both report 0 Class (B) orphans against
  scripts/check_image_referential_integrity.py. Class (B) promoted from
  warning-only to blocking in the same PR to lock against regression.'
pr_refs:
  - 318
severity: low
slug: v2-metric-facts-source-locator-img-id-has-no-referential-int
source: legacy
status: resolved
title: '`v2_metric_facts.source_locator.img_id` Has No Referential Integrity'
touches:
  - scripts/check_image_referential_integrity.py
updated: '2026-04-28'
---

### Problem

`img_id` is stored as a value inside a JSONB `source_locator` column (`sql/09_v2_schema.sql:420`), not as a foreign key. After the sql/34 fix, new facts written by `persist_pipeline_result` use the stable DB img_id. However, historical facts written before the fix likely contain orphaned img_ids pointing to rows that were collapsed by the dedup migration.

### Suggested Fix

Add a scheduled integrity-check script, or promote `img_id` to a dedicated FK column on `v2_metric_facts`. The latter is the more robust fix but requires a migration and application-layer changes.

### Diagnostic Script (2026-04-19)

`scripts/check_image_referential_integrity.py` scans for orphan `img_id` values and exits non-zero when any are found. Baseline against the local dev DB on 2026-04-19: **9 orphan facts across 4 docs** (doc_id=1546: 4, doc_id=1545: 2, doc_id=1551: 2, doc_id=1539: 1). These are historical facts predating the `sql/34` dedup migration. Prod has not been scanned yet. Cleanup strategy (delete orphan facts vs. rewrite `source_locator.img_id` to NULL vs. leave as-is) is still open.

### Extended to Three Classes (2026-04-19, commit `d1430d9`)

The script now reports three classes and is wired into the integration-tests CI job (`.github/workflows/ci.yml`):

- **Class (A)** — `source_type='chart'` facts with null `source_locator.img_id`. **Blocking** (exit 1); baseline 0; protects the `ChartFactBridgeStage` invariant.
- **Class (B)** — orphaned `img_id` refs (this issue). Warning-only.
- **Class (C)** — asset rows with `file_path` outside `data/` or missing on disk. Warning-only; tracked under Issue #34.

`tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` locks the Class (A) invariant at unit-test level.

### Resolution (2026-04-28)

Closed as a fragment-only resolution per `project_fragment_only_closure_pattern`. No data migration required.

**Verification.** `scripts/check_image_referential_integrity.py` was rerun after the 2026-04-23 chart-presence pivot (#147), which removed the per-value chart `v2_metric_facts` emission path that historically wrote `source_locator.img_id`-bearing rows. Counts now:

- **Neon prod (`DATABASE_URL` in `.env`)**: 0 Class (B) orphans (down from 9 across 4 docs at the 2026-04-19 baseline). The 4 affected docs (1539, 1545, 1546, 1551) appear to have washed through normal re-extraction or DB churn between 2026-04-19 and 2026-04-28.
- **Local Docker test DB (`TEST_DATABASE_URL`)**: 0 Class (B) orphans (test DB carries no fact data of its own).

**Lock-in.** Class (B) promoted from warning-only to blocking in `scripts/check_image_referential_integrity.py` so a single regression on any DB the script is pointed at fails CI's integration-tests job. Class (A) blocking semantics and the unit-level invariant in `tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` are unchanged. Class (C) remains warning-only and continues to track separately under issue #34.

**Why no migration.** The chart-presence pivot eliminated the upstream code path that wrote chart facts with `source_locator.img_id`. Future chart presence flows through `v2_image_metric_presence` and `v2_image_metric_confirmations`, neither of which depends on `source_locator`. With both observed populations already at 0 and no upstream writer remaining, the remaining cleanup options (delete vs. NULL-out vs. promote to FK column) are all no-ops on a no-orphan dataset.

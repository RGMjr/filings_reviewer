---
autonomy: skip
discovered: '2026-04-18'
estimated: M
id: 24
note: 'Scope reduced to historical advisory-fact hygiene after 2026-04-24
  presence-first pivot: presence rows (v2_text_metric_presence,
  v2_image_metric_presence) do not rely on source_locator.img_id; orphans live only
  in legacy advisory v2_metric_facts. Not on the presence-pivot critical path.'
severity: low
slug: v2-metric-facts-source-locator-img-id-has-no-referential-int
source: legacy
status: open
title: '`v2_metric_facts.source_locator.img_id` Has No Referential Integrity'
touches: []
updated: '2026-04-24'
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

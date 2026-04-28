---
autonomy: safe
discovered: '2026-04-27'
estimated: S
id: 116
pr_refs:
- 268
severity: low
slug: 8k-e2e-pipeline-test-for-exhibit-content
source: legacy
status: resolved
title: Missing E2E Pipeline Test for 8-K Exhibit Metric Extraction
touches:
- tests/integration/extraction_v2/
updated: '2026-04-27'
---

### Problem

The integration test added with the legacy-058 fix (`tests/integration/filing_fetcher/test_8k_exhibit_fetch.py`) validates only that the fetcher writes the combined HTML correctly. It does not run the full V2 pipeline and cannot assert that segment count is non-trivial (> 20) or that at least one `v2_metric_facts` row is produced from the exhibit content. The pipeline-level assertion was explicitly deferred from the legacy-058 PR scope.

### Next Steps

- Add an E2E test in `tests/integration/extraction_v2/` that feeds a Samsara-shaped 8-K fixture (primary cover page + exhibit 99.1 with known earnings language) through `process_filing`.
- Assert: (i) `len(result.segments) > 20`, (ii) at least one `MetricFact` is produced whose source segment text contains exhibit-sourced language (e.g. "total revenue" or "ARR").
- Use the existing `data/gold_standard/` fixture pattern. Samsara 2025-08-21 (CIK 1642545) is the canonical example — a sanitized copy of the exhibit HTML is the recommended fixture source.

### Resolution

Added `tests/integration/extraction_v2/test_8k_exhibit_e2e_pipeline.py` (PR #268). The test feeds a sanitized Samsara 8-K fixture (`data/gold_standard/Samsara_Inc_8K_2025-08-21/filing.html`, 16 KB, combined primary cover + exhibit 99.1 via `<!-- EXHIBIT-99.1 -->` separator) through `process_filing` and asserts: (i) `len(result.segments) > 20` and (ii) at least one `MetricFact` with exhibit-sourced language (`"total revenue"`, `"ARR"`, etc.) in its `evidence_pack`. The fixture is test-only — no `extracted_values.csv` or `metadata.json`, so the gold-standard validator ignores it. All 6 test cases pass in 1.06 s (no DB required). Unit suite unaffected (3878 passed).

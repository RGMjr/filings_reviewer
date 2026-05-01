---
id: 386
source: gh
slug: chart-e2e-mock-call-count
title: "test_chart_extraction_produces_chart_data: mock_client.call_count == 2, expected 1"
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-04-30
updated: 2026-04-30
gh_issue: 386
note: chart_e2e integration test fails on clean main; mock vision client is invoked twice when test expects 1.
---

### Problem

`tests/integration/test_chart_e2e.py::TestChartExtractionE2E::test_chart_extraction_produces_chart_data` fails on clean main (verified via `git stash --keep-index` against `8390f71`). The mock vision client is invoked twice when the test asserts a single call. Blocks `pytest -x -q` for anyone running the full suite locally; deselectable but real.

### Next Steps

- Trace where the duplicate `MockVisionClient.analyze_image` call originates — likely a chart stage running classify + OCR vs. the test expecting only one of those.
- Either update the test to reflect the current call shape, or fix the production stage if the second call is wasteful.

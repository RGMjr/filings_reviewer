---
id: 381
source: gh
slug: chart-e2e-mock-call-count-regression
title: "test_chart_extraction_produces_chart_data: MockVisionClient.call_count == 2 (expected 1)"
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/stages/ocr_extraction.py
  - tests/integration/test_chart_e2e.py
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 381
note: OCRExtractionStage now calls analyze_image twice per CHART asset; mock test expects one. Likely tied to PR #360 per-site vision env split.
---

### Problem

`tests/integration/test_chart_e2e.py::TestChartExtractionE2E::test_chart_extraction_produces_chart_data` fails on clean main: the test asserts `mock_client.call_count == 1` for a single CHART-classified asset processed through `OCRExtractionStage`, but the actual count is `2`. Pre-existing — reproduces on a clean checkout — surfaced while running the full pytest suite during `/commit-proj` for the resume-button PR (PR for gh-313 UI surface).

Likely correlated with the recent per-site vision model env knobs (commit `7768cb7` / PR #360) which split full-page OCR and prescan into separate vision-client paths. The chart pipeline now appears to invoke `analyze_image` twice for the same chart, but the test mock still expects one call.

### Next Steps

- Decide whether the second call is intentional (e.g. re-prompt with refined `detected_metrics`) or accidental (double-dispatch). If intentional, update the test's expected count + add a comment naming the two stages. If accidental, root-cause and fix in `OCRExtractionStage.process()` / chart sub-pipeline.
- Until decided: this test masks future chart-pipeline regressions, so prioritise.

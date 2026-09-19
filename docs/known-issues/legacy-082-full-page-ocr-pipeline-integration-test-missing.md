---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 82
severity: low
slug: full-page-ocr-pipeline-integration-test-missing
source: legacy
status: archived
title: Full-Page-OCR Pipeline Integration Test Missing
touches:
- tests/integration/extraction_v2/test_full_page_ocr_pipeline.py
updated: '2026-04-25'
---

### Problem

Phase-3 unit tests exercise `ImageTriageStage._detect_full_page_scan_filing`, `OCRExtractionStage.process_full_page_scan`, and `_prescan_ambiguous_images` individually. No integration test runs the full `V2Pipeline` on a page-scan HTML fixture and asserts that `v2_segments` rows with `source_type='image_ocr'` land, downstream `v2_metric_facts` get produced, and the chart two-pass populates `chart_data` where expected. Local test DB (`filings_analysis_test`) has 0 filings so we couldn't seed from real data.

### Next Steps

1. Create a minimal fixture: a stub HTML document with a handful of `<img>` tags pointing at portrait-page-sized dummy JPGs, seeded under `tests/integration/fixtures/full_page_ocr/`.
2. Add `tests/integration/extraction_v2/test_full_page_ocr_pipeline.py` that constructs a `PipelineConfig(enable_full_page_ocr=True)`, runs `V2Pipeline.process` with a mocked `VisionClient`, and asserts segment + fact + image-asset state end-to-end.
3. Alternative: once the prod rollout backfill completes on a real PayPal 8-K, capture its vision responses as VCR cassettes and build the fixture from that.

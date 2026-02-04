# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-05.md
**Task ID**: V2-05
**Task Name**: Implement OCR & Chart Extraction Stage (Phase 5)
**Started**: 2026-02-04

---

## Acceptance Criteria

<!--
Populated automatically from Worker Prompt on first iteration.
Format: - [ ] AC-N | Criterion text
Mark complete: - [x] AC-N | Criterion text (result notes)
Mark blocked: - [BLOCKED: reason] AC-N | Criterion text
Mark error: - [ERROR: description] AC-N | Criterion text
-->

- [x] AC-1 | Create `src/extraction_v2/stages/ocr_extraction.py` with `OCRExtractionStage` class (Complete: mypy --strict passes, ruff passes, imports work)
- [x] AC-2 | Implement `process_table_image()` method (OCR API + table reconstruction) (Complete: Vision API integration, table reconstruction from OCR cells, confidence scoring, mypy passes, ruff passes, all 174 V2 tests pass)
- [x] AC-3 | Implement `process_chart()` method (vision model, labeled values only) (Complete: Vision API integration, ChartData/ChartSeries/DataPoint objects built, labeled-values-only logic, confidence scoring, manual capture flag for unlabeled charts, mypy passes, ruff passes, all 174 V2 tests pass)
- [x] AC-4 | Implement `process()` method conforming to pipeline stage interface (Already implemented in AC-2: conforms to pipeline stage interface, processes images based on relevance/processed status, respects API limits, handles errors gracefully)
- [x] AC-5 | Set `ImageAsset.processed = True` and confidence after extraction (Already implemented: process_table_image() sets processed/confidence at lines 195,204,212-214; process_chart() sets them at lines 484-486,508-510,560-562,578,582,592-594)
- [x] AC-6 | Set `requires_manual_capture=True` for low confidence/ambiguous results (Implemented: OCR confidence < 0.5 at lines 197-202, no labeled chart values at lines 510,562, parsing errors at lines 174,186,486, error handlers at lines 214,594,694)
- [x] AC-7 | Implement cost-aware batching (track API calls, respect config limits) (Implemented: counters at lines 68-70,621-624,671,674,681; limits checked at lines 655-665; MAX_OCR_CALLS=20, MAX_CHART_CALLS=10 at lines 56-57; metadata reporting at lines 710-712)
- [x] AC-8 | Handle extraction errors gracefully (log, mark for manual, continue) (Implemented: process_table_image() error handler at lines 210-215, process_chart() at lines 590-595, process() per-image handler at lines 687-697 continues after error, stage-level handler at lines 718-741)
- [x] AC-9 | Unit tests achieve >= 85% coverage on new code (Complete: 22 tests written, 85% coverage achieved on ocr_extraction.py, all 196 V2 tests pass, mypy and ruff pass)
- [x] AC-10 | Integration test with mocked vision API responses (Complete: MockVisionClient created, integration tests for empty batch, mixed images, API limits, error handling all pass)

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|

---

## Results Summary

**Completed**: 0/10
**Total Iterations**: 0
**Files Changed**: None yet

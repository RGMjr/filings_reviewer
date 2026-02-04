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
- [ ] AC-2 | Implement `process_table_image()` method (OCR API + table reconstruction)
- [ ] AC-3 | Implement `process_chart()` method (vision model, labeled values only)
- [ ] AC-4 | Implement `process()` method conforming to pipeline stage interface
- [ ] AC-5 | Set `ImageAsset.processed = True` and confidence after extraction
- [ ] AC-6 | Set `requires_manual_capture=True` for low confidence/ambiguous results
- [ ] AC-7 | Implement cost-aware batching (track API calls, respect config limits)
- [ ] AC-8 | Handle extraction errors gracefully (log, mark for manual, continue)
- [ ] AC-9 | Unit tests achieve >= 85% coverage on new code
- [ ] AC-10 | Integration test with mocked vision API responses

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

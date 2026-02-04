# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-04.md
**Task ID**: V2-04
**Task Name**: Implement Image Triage Stage (Phase 4)
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

- [x] AC-1 | Create `src/extraction_v2/stages/image_triage.py` with `ImageTriageStage` class
- [x] AC-2 | Implement `classify_image()` method using filename patterns, nearby text, and dimensions
- [x] AC-3 | Classify images into: CHART, TABLE_IMAGE, DECORATIVE, LOGO, SIGNATURE, UNKNOWN
- [x] AC-4 | For CHART images, detect chart type (BAR, LINE, PIE, STACKED_BAR, AREA)
- [x] AC-5 | Implement `score_relevance()` with section-aware scoring (MD&A +0.2, Risk Factors +0.1)
- [x] AC-6 | Implement `triage_images()` batch method that processes all images in context
- [x] AC-7 | Filter decorative images more aggressively (aspect ratio, repeated patterns)
- [x] AC-8 | Set `requires_manual_capture=True` for ambiguous images
- [x] AC-9 | Implement `process()` method conforming to pipeline stage interface
- [x] AC-10 | Unit tests achieve ≥85% coverage on new code (achieved 94%)
- [ ] AC-11 | Integration test with real SEC filing images (from test fixtures)

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| 1 | AC-1 to AC-10 | ✅ Complete | Created ImageTriageStage with classify_image(), detect_chart_type(), score_relevance(), triage_images(), process() methods |

---

## Results Summary

**Completed**: 10/11
**Total Iterations**: 1
**Files Changed**:
- src/extraction_v2/stages/image_triage.py (created - 500+ lines)
- src/extraction_v2/stages/__init__.py (updated - export ImageTriageStage)
- tests/unit/extraction_v2/test_image_triage.py (created - 47 tests)

**Verification**:
- 47/47 tests passing
- 94% coverage on image_triage.py (exceeds 85% target)
- mypy --strict passes
- ruff lint passes

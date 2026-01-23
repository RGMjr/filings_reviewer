# Development Plan

**Worker Prompt**: docs/V2_IMPLEMENTATION_ROADMAP.md (Phase 1: Ingestion)
**Task ID**: V2-PHASE-1
**Started**: 2026-01-23

---

## Acceptance Criteria

<!--
Populated automatically from Worker Prompt on first iteration.
Format: - [ ] AC-N | Criterion text
Mark complete: - [x] AC-N | Criterion text (result notes)
Mark blocked: - [BLOCKED: reason] AC-N | Criterion text
Mark error: - [ERROR: description] AC-N | Criterion text
-->

- [ ] AC-1 | Create `src/extraction_v2/stages/__init__.py` module package
- [ ] AC-2 | Create `src/extraction_v2/stages/ingestion.py` with IngestionStage class
- [ ] AC-3 | Implement lxml-based HTML parser with `lxml.html.parse()`
- [ ] AC-4 | Generate stable XPath locators for every HTML element
- [ ] AC-5 | Port paragraph detection from V1 (min 50 chars, max 10000)
- [ ] AC-6 | Port table detection with div-wrapper deduplication from V1
- [ ] AC-7 | Add `[CELL]` and `[ROW]` markers to table text output
- [ ] AC-8 | Port definition/methodology block detection from V1
- [ ] AC-9 | Extract ImageAsset objects with nearby text context
- [ ] AC-10 | Create Segment objects with dom_locator (XPath), segment_type, text, sequence
- [ ] AC-11 | Create Document object with filing metadata
- [ ] AC-12 | Update pipeline.py to use real IngestionStage (replace stub)
- [ ] AC-13 | Create unit tests in `tests/unit/extraction_v2/test_ingestion.py`
- [ ] AC-14 | Achieve 80%+ code coverage on new ingestion module
- [ ] AC-15 | All existing tests pass (pytest -v)
- [ ] AC-16 | Type checking passes (mypy src/extraction_v2/stages/ --strict)

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| 1 | - | - | - |

---

## Results Summary

<!-- Populated on DEVELOPMENT_COMPLETE -->

**Completed**: [Date]
**Total Iterations**: [N]
**Files Changed**: [List]
**Test Results**: [Pass/Fail + coverage]

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

- [x] AC-1 | Create `src/extraction_v2/stages/__init__.py` module package (module created with docstring, import successful)
- [x] AC-2 | Create `src/extraction_v2/stages/ingestion.py` with IngestionStage class (class created, imports from pipeline.py, all 45 tests pass)
- [x] AC-3 | Implement lxml-based HTML parser with `lxml.html.parse()` (implemented _parse_html method with lxml.html.fromstring, handles malformed/empty HTML, 8/8 tests pass)
- [x] AC-4 | Generate stable XPath locators for every HTML element (_generate_xpath method implemented with position-based XPath, 6/6 tests pass, mypy --strict passes)
- [x] AC-5 | Port paragraph detection from V1 (min 50 chars, max 10000) (_extract_paragraph_segments implemented, filters by length, skips nested tables, 8/8 tests pass)
- [x] AC-6 | Port table detection with div-wrapper deduplication from V1 (_extract_table_segments, _should_skip_div_wrapper implemented, 7/7 tests pass, 74 total tests pass)
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
| 1 | AC-1 | Complete | Created stages/__init__.py with docstring |
| 2 | AC-2 | Complete | Created IngestionStage class with process method, resolved circular import via TYPE_CHECKING |
| 3 | AC-3 | Complete | Implemented lxml HTML parser with error handling (empty files, malformed HTML), 53 tests pass |
| 4 | AC-4 | Complete | Implemented _generate_xpath method with position-based XPath, 6 comprehensive tests, stable across re-parsing, 59 tests pass |
| 5 | AC-5 | Complete | Implemented _extract_paragraph_segments with V1 logic: min/max length filters, skip tables/nested divs, normalize whitespace, 67 tests pass |
| 6 | AC-6 | Complete | Implemented table detection with div-wrapper deduplication: _extract_table_segments, _should_skip_div_wrapper, 7 new tests, 74 total tests pass |

---

## Results Summary

<!-- Populated on DEVELOPMENT_COMPLETE -->

**Completed**: [Date]
**Total Iterations**: [N]
**Files Changed**: [List]
**Test Results**: [Pass/Fail + coverage]

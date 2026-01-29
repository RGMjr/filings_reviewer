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
- [x] AC-7 | Add `[CELL]` and `[ROW]` markers to table text output (_extract_table_text_with_markers implemented, 10/10 tests pass, 84 total tests pass, mypy --strict passes)
- [x] AC-8 | Port definition/methodology block detection from V1 (_classify_segment_type detects DEFINITION and METHODOLOGY segment types, 9/9 tests pass, 93 total tests pass, mypy --strict passes)
- [x] AC-9 | Extract ImageAsset objects with nearby text context (_extract_image_assets implemented with decorative filtering, caption extraction, relevance scoring, XPath locators, 9/9 tests pass, 102 total tests pass, mypy --strict passes)
- [x] AC-10 | Create Segment objects with dom_locator (XPath), segment_type, text, sequence (unified sequencing with document order sorting, all segments have XPath locators, 102/102 tests pass, mypy --strict passes)
- [x] AC-11 | Create Document object with filing metadata (Document created with doc_id and html_path, 102/102 tests pass, mypy --strict passes)
- [x] AC-12 | Update pipeline.py to use real IngestionStage (replace stub) (already complete: pipeline imports and instantiates real IngestionStage from stages/ingestion.py, 102 tests pass, mypy --strict passes)
- [x] AC-13 | Create unit tests in `tests/unit/extraction_v2/test_ingestion.py` (57 comprehensive tests created covering all acceptance criteria, all tests pass)
- [x] AC-14 | Achieve 80%+ code coverage on new ingestion module (93% coverage: 299/321 lines covered)
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
| 7 | AC-7 | Complete | Implemented _extract_table_text_with_markers with cell/row boundary markers: 10 comprehensive tests, 84 total tests pass, mypy --strict passes |
| 8 | AC-8 | Complete | Definition/methodology detection already implemented: _classify_segment_type method detects DEFINITION/METHODOLOGY segment types using V1 patterns, 9 tests pass, 93 total tests, mypy --strict passes |
| 9 | AC-9 | Complete | Implemented image extraction: _extract_image_assets with decorative filtering, caption extraction from figcaption, nearby text from siblings, relevance scoring based on metric keywords, XPath locators, 9 comprehensive tests, 102 total tests pass, mypy --strict passes |
| 10 | AC-10 | Complete | Implemented unified segment sequencing: segments from paragraphs and tables are sorted by document order using lxml element position, sequence numbers assigned in order, all segments have dom_locator (XPath), segment_type, text, sequence fields, 102 tests pass, mypy --strict passes |
| 11 | AC-11 | Complete | Document object already implemented in ingestion.py process() method (lines 856-861): creates Document with doc_id from filing_id and html_path from context, all 102 tests pass, mypy --strict passes |
| 12 | AC-12 | Complete | Pipeline already imports and instantiates real IngestionStage from stages/ingestion.py (no stub replacement needed), verified via Python import test, 102 tests pass, mypy --strict passes |
| 13 | AC-13 | Complete | Unit tests already exist in test_ingestion.py with 57 comprehensive test cases covering all ACs (3-9), all pass, ingestion.py has 93% coverage |
| 14 | AC-14 | Complete | Coverage verified at 93% (299/321 lines covered), exceeds 80% requirement |

---

## Results Summary

<!-- Populated on DEVELOPMENT_COMPLETE -->

**Completed**: [Date]
**Total Iterations**: [N]
**Files Changed**: [List]
**Test Results**: [Pass/Fail + coverage]

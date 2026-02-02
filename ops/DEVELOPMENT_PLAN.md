# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-PHASE-2.md
**Task ID**: V2-PHASE-2
**Task Name**: Section Classification Stage
**Started**: 2026-02-02

---

## Acceptance Criteria

<!--
Populated automatically from Worker Prompt on first iteration.
Format: - [ ] AC-N | Criterion text
Mark complete: - [x] AC-N | Criterion text (result notes)
Mark blocked: - [BLOCKED: reason] AC-N | Criterion text
Mark error: - [ERROR: description] AC-N | Criterion text
-->

- [x] AC-1 | Create `src/extraction_v2/stages/section_classification.py` with `SectionClassificationStage` class (created with full structure, mypy --strict passes)
- [ ] AC-2 | Implement heading detection (font/bold, all-caps, numbered sections, known patterns)
- [ ] AC-3 | Detect COVER section (first segments before Risk Factors/TOC)
- [ ] AC-4 | Detect RISK_FACTORS section (heading pattern + high-value segment flag)
- [ ] AC-5 | Detect MDA section ("Management's Discussion", "MD&A")
- [ ] AC-6 | Detect BUSINESS section (company description, products)
- [ ] AC-7 | Detect FINANCIALS section (financial statements)
- [ ] AC-8 | Detect NOTES section (footnotes to financial statements)
- [ ] AC-9 | Detect EXHIBITS and SIGNATURES sections (mark as filterable)
- [ ] AC-10 | Assign `section_type` enum to each Segment in context.segments
- [ ] AC-11 | Build hierarchical `section_path` list for each Segment
- [ ] AC-12 | Wire into pipeline - replace stub in `pipeline.py`
- [ ] AC-13 | Unit tests with ≥90% coverage on section_classification.py
- [ ] AC-14 | Integration test with real SEC filing (from existing fixtures)

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| 1 | AC-1 | ✅ Complete | Created section_classification.py with full stage implementation, mypy --strict passes |

---

## Previous Tasks

### V2-10: Table Reconstruction ✅ COMPLETE (2026-01-29)
- All 10 ACs met
- 96% coverage, 25 tests
- Completion report: ops/completion-reports/V2-10_completion.md

### V2-11: Compute header_path ✅ ABSORBED BY V2-10
- Functionality implemented as `_compute_paths()` in table_reconstructor.py:273-318
- Tests in `TestPathComputation` class
- Worker prompt archived to `docs/archive/worker-prompts/`

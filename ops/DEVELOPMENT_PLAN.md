# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-PHASE-9.md
**Task ID**: V2-PHASE-9
**Task Name**: Fact Construction Stage
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

- [ ] AC-1 | `src/extraction_v2/stages/fact_construction.py` exists
- [ ] AC-2 | `FactConstructionStage.process()` transforms `BoundValue` → `MetricFact`
- [ ] AC-3 | Confidence scoring: base from binding + section bonus + penalties
- [ ] AC-4 | `EvidencePack` generated with snippet_html for table sources
- [ ] AC-5 | `EvidencePack` generated with context_before/after for text sources
- [ ] AC-6 | `source_type` correctly set (HTML_TABLE, TEXT, CHART)
- [ ] AC-7 | `source_locator` populated from bound value
- [ ] AC-8 | Pipeline integration: stage exported in `__init__.py`
- [ ] AC-9 | Tests in `tests/unit/extraction_v2/test_fact_construction.py`
- [ ] AC-10 | Coverage ≥80% for new module
- [ ] AC-11 | `mypy --strict` passes on new module
- [ ] AC-12 | `ruff check` passes

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| - | - | - | Awaiting first iteration |

---

## Previous Tasks

### V2-PHASE-8: Period Inference Stage ✅ COMPLETE (2026-02-04)
- All ACs met
- Committed as 4e68bf4

### V2-PHASE-7-IMPROVEMENTS: Value Binding Improvements ✅ COMPLETE (2026-02-04)
- All 10 ACs met
- 44 tests, 93% coverage

### V2-PHASE-7: Value Binding Stage ✅ COMPLETE (2026-02-04)
- All 16 ACs met
- 92% coverage, 40 tests
- Core implementation done

### V2-PHASE-6: Candidate Generation ✅ COMPLETE (2026-02-03)
- All ACs met
- 96% coverage, 42 tests

### V2-PHASE-3: Table Reconstruction ✅ COMPLETE (2026-02-02)
- All 11 ACs met
- 87% coverage, 11 tests

### V2-PHASE-2: Section Classification ✅ COMPLETE (2026-02-02)
- All 14 ACs met
- 93% coverage, 49 tests


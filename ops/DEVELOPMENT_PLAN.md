# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-PHASE-7-IMPROVEMENTS.md
**Task ID**: V2-PHASE-7-IMPROVEMENTS
**Task Name**: Value Binding Stage Improvements
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

- [x] AC-1 | `_parse_number()` handles "billion", "B", "$1.2B" correctly (already implemented, test added)
- [x] AC-2 | `ValueBindingStage.__init__()` accepts `proximity_window` parameter (added with default=100)
- [x] AC-3 | `_find_nearby_numbers()` uses configurable window (now uses self.proximity_window)
- [x] AC-4 | `_find_sentence_bounds()` method exists and works (implemented with regex)
- [x] AC-5 | Same-sentence bindings get confidence bonus (SAME_SENTENCE_BONUS = 0.1)
- [x] AC-6 | All existing tests still pass (44 tests pass)
- [x] AC-7 | New tests for all three improvements (test_parse_billion_variants, test_configurable_proximity_window, test_same_sentence_bonus, test_sentence_boundary_detection)
- [x] AC-8 | Coverage remains ≥90% (93% coverage)
- [x] AC-9 | `mypy --strict` passes (success: no issues)
- [x] AC-10 | `ruff check` passes (all checks passed)

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| 1 | AC-1 to AC-10 | Complete | All acceptance criteria met in single iteration |

---

## Previous Tasks

### V2-PHASE-7: Value Binding Stage ✅ COMPLETE (2026-02-04)
- All 16 ACs met
- 92% coverage, 40 tests
- Core implementation done, improvements identified

### V2-PHASE-6: Candidate Generation ✅ COMPLETE (2026-02-03)
- All ACs met
- 96% coverage, 42 tests
- Committed to v2-rewrite

### V2-PHASE-3: Table Reconstruction ✅ COMPLETE (2026-02-02)
- All 11 ACs met
- 87% coverage, 11 tests
- Completion report: ops/completion-reports/V2-PHASE-3_completion.md

### V2-PHASE-2: Section Classification ✅ COMPLETE (2026-02-02)
- All 14 ACs met
- 93% coverage, 49 tests
- Merged to v2-rewrite: commit 614ea5b

### V2-10: Table Reconstruction ✅ COMPLETE (2026-01-29)
- All 10 ACs met
- 96% coverage, 25 tests
- Completion report: ops/completion-reports/V2-10_completion.md

### V2-11: Compute header_path ✅ ABSORBED BY V2-10
- Functionality implemented as `_compute_paths()` in table_reconstructor.py:273-318
- Tests in `TestPathComputation` class
- Worker prompt archived to `docs/archive/worker-prompts/`


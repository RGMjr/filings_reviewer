# Development Plan

**Worker Prompt**: docs/worker-prompts/WORKER_PROMPT_TASK_V2-PHASE-3.md
**Task ID**: V2-PHASE-3
**Task Name**: Table Reconstruction Stage (Wire Existing)
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

- [ ] AC-1 | Create `src/extraction_v2/stages/table_reconstruction.py` with `TableReconstructionStage` class
- [ ] AC-2 | Import and use existing `TableReconstructor` from `src/extraction_v2/table_reconstructor.py`
- [ ] AC-3 | Process each table segment from `context.segments` where `segment_type == SegmentType.TABLE`
- [ ] AC-4 | Parse segment's `raw_html` with BeautifulSoup to get table element
- [ ] AC-5 | Call `reconstructor.reconstruct(table_elem)` to get `Table` object
- [ ] AC-6 | Store reconstructed `Table` objects in `context.tables` list
- [ ] AC-7 | Link each `Table` back to its source `Segment` (via segment_id or reference)
- [ ] AC-8 | Wire into pipeline - replace stub in `pipeline.py` with import
- [ ] AC-9 | Update `src/extraction_v2/stages/__init__.py` to export the new stage
- [ ] AC-10 | Unit tests with ≥90% coverage on table_reconstruction.py
- [ ] AC-11 | Integration test verifying tables are reconstructed from ingested segments

---

## Progress Log

<!-- Automatically updated each iteration -->

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|

---

## Previous Tasks

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


# Development Plan

**Task ID**: BEYOND-SEC-PHASE-A
**Task Name**: Transcript Support (Beyond SEC — Phase A)
**Status**: NOT STARTED (planning only)
**Design Doc**: `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md`

---

## Acceptance Criteria

- [ ] AC-1 | Value binding uses wider proximity windows when `document_type='transcript'` (+10% recall est.)
- [ ] AC-2 | Sentence-level value binding for text sources (+5% recall est.)
- [ ] AC-3 | FP filter relaxes segment-level co-occurrence rules for transcripts (+5% recall est.)
- [ ] AC-4 | Period inference matches "FY'25" / "fiscal year '25" patterns (+5% recall est.)
- [ ] AC-5 | Period inference uses `document_date` fallback when no period found (+5% recall est.)
- [ ] AC-6 | Period inference matches standalone "Q4" using document_date year
- [ ] AC-7 | Transcript converter (text→HTML) hardened from spike version, splits large paragraphs into sentences
- [ ] AC-8 | HuggingFace `DocumentSource` implementation for kurry dataset
- [ ] AC-9 | Schema migration: `document_type`, `ticker`, `document_date`, `transcript_source` on `filings`; relaxed constraints
- [ ] AC-10 | Integration tests: end-to-end transcript pipeline on 5+ transcripts
- [ ] AC-11 | Measured recall >= 50% on existing 77 manual annotations
- [ ] AC-12 | Precision remains >= 60% (no regression from current 63%)

---

## Progress Log

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| — | — | — | Not started |

---

## Pre-Work Completed

- Research spike complete (8a033b2): 6 design docs, 22 sample transcripts, 77 annotations
- Pipeline config presets (b57652a): `PipelineConfig.for_transcript()` with document_type/document_date
- Baseline: R=22.1%, P=63.0%, F1=32.7% on 8 annotated transcripts
- See `docs/analysis/spike/gap_analysis.md` for stage-by-stage bottleneck analysis

---

## Previous Tasks

### V2-PHASE-12: Database Persistence ✅ COMPLETE (2026-02-04)
- All 12 ACs met
- persistence.py 750 lines, 18 tests pass, 93% coverage
- Committed as fda152b

### V2-PHASE-11: Validation & Review Routing Stage ✅ COMPLETE (2026-02-04)
- All 11 ACs met
- 31 tests, 98% coverage
- Committed as 243f518

### V2-PHASE-10: Deduplication Stage ✅ COMPLETE (2026-02-04)
- All 10 ACs met
- 35 tests, 96% coverage
- Committed as 5049fb2

### V2-PHASE-9: Fact Construction Stage ✅ COMPLETE (2026-02-04)
- All 12 ACs met
- 22 tests, 94% coverage
- Committed as 6a26eba

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

### V2-05: OCR & Chart Extraction ✅ COMPLETE (2026-02-03)
- All 10 ACs met
- 85% coverage, 22 tests
- Committed to main

### V2-04: Image Triage ✅ COMPLETE (2026-02-03)
- All ACs met
- 94% coverage
- Committed to main

### V2-PHASE-3: Table Reconstruction ✅ COMPLETE (2026-02-02)
- All 11 ACs met
- 87% coverage, 11 tests

### V2-PHASE-2: Section Classification ✅ COMPLETE (2026-02-02)
- All 14 ACs met
- 93% coverage, 49 tests

# Development Plan

**Task ID**: BEYOND-SEC-PHASE-A
**Task Name**: Transcript Support (Beyond SEC — Phase A)
**Status**: NEARLY COMPLETE (11/12 ACs met)
**Design Doc**: `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md`

---

## Acceptance Criteria

- [x] AC-1 | Value binding uses wider proximity windows when `document_type='transcript'` (+10% recall est.)
- [x] AC-2 | Sentence-level value binding for text sources (+5% recall est.)
- [x] AC-3 | FP filter relaxes segment-level co-occurrence rules for transcripts (+5% recall est.)
- [x] AC-4 | Period inference matches "FY'25" / "fiscal year '25" patterns (+5% recall est.)
- [x] AC-5 | Period inference uses `document_date` fallback when no period found (+5% recall est.)
- [x] AC-6 | Period inference matches standalone "Q4" using document_date year
- [x] AC-7 | Transcript converter (text→HTML) hardened from spike version, splits large paragraphs into sentences
- [x] AC-8 | HuggingFace `DocumentSource` implementation for kurry dataset
- [x] AC-9 | Schema migration: `document_type`, `ticker`, `document_date`, `transcript_source` on `filings`; relaxed constraints
- [ ] AC-10 | Integration tests: end-to-end transcript pipeline on 5+ transcripts
- [x] AC-11 | Measured recall >= 50% on existing 77 manual annotations (achieved: 59.7%)
- [x] AC-12 | Precision remains >= 60% (achieved: 69.7%)

---

## Progress Log

| Iteration | Criterion | Status | Notes |
|-----------|-----------|--------|-------|
| 6a37369 | AC-1 thru AC-9 | Done | Pipeline tuning, converter, infra |
| 0cdcd9d | AC-11, AC-12 | Done | R=54.5%, P=60.0%, F1=57.1% |
| 5a1c2ee | AC-12 hardened | Done | P=71.9% via 4 FP rules, 32 new tests |
| c733aef | Phase A+ recall | Done | R=53%→60%, keyword expansion + binding fixes |

---

## Post-Phase A: Precision Hardening (5a1c2ee)

Four FP reduction rules added:
1. **Bare small-number filter** — count values <50 without scale suffix filtered in transcript mode
2. **Currency-on-count-metric block** — $ values rejected on MAU/DAU/active_customers/customers_period_end/new_customers/large_customers
3. **Cross-metric dedup** — same value+segment mapped to multiple metric IDs → keep highest confidence
4. **Scoring fix** — run_poc.py checks unit compatibility (currency≠count)

Result: P=60%→72%, FP 28→16, F1=57%→61%. SEC gold standard unchanged.

---

## Remaining Work

### Phase A Cleanup
- **AC-10**: Integration tests for transcript pipeline (not yet created)

### Phase A+ (Recall Improvement — In Progress)
- [x] **Non-SaaS keyword expansion** (c733aef): TMUS postpaid/prepaid, PYPL debit card, MSFT enterprises/organizations, META magnitude patterns — R=53%→60%
- [x] **Word-form number parsing** (c733aef): "one billion", "two million" etc. — 3 FNs recovered
- [x] **is_percentage_format bug** (c733aef): "1.4 million" no longer misclassified as percentage
- [x] **MIN_PARAGRAPH_CHARS** (c733aef): configurable per pipeline, 30 for transcripts (was 50)
- [ ] **PYPL $224M transcript bug**: converter produces "$224 million" for MAU count
- [ ] **Q&A section stricter filtering**: analyst questions contain speculative numbers
- [ ] **Remaining keyword gaps**: META family-of-apps, MSFT (text missing from HTML), ADSK vocabulary
- Current: R=59.7%, P=69.7%, F1=64.3% | Target: R≥65%, P≥70%, F1≥67%

### Phase B (Expanded Coverage)
- FMP API source (`FMPTranscriptSource`) for broader transcript corpus
- Company matching by ticker
- Web UI: document type filter, transcript viewer
- Schema migration applied to production DB

### Phase C (Presentation Support)
- PDF-to-HTML converter (pdfplumber/docling)
- SEC 8-K presentation source
- Chart pipeline tuning for presentation charts
- Target: >40% recall on presentations

### Phase D (Production Readiness)
- Monitoring/alerting for new document types
- Batch processing scripts for periodic transcript ingestion
- Documentation updates

---

## Pre-Work Completed

- Research spike complete (8a033b2): 6 design docs, 22 sample transcripts, 77 annotations
- Pipeline config presets (b57652a): `PipelineConfig.for_transcript()` with document_type/document_date
- Baseline: R=22.1%, P=63.0%, F1=32.7% on 8 annotated transcripts

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

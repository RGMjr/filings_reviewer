# Development Plan

**Task ID**: BEYOND-SEC-PHASE-A
**Task Name**: Transcript Support (Beyond SEC — Phase A)
**Status**: COMPLETE (12/12 ACs met)
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
- [x] AC-10 | Integration tests: end-to-end transcript pipeline on 5+ transcripts (3781cc7, 2026-02-19)
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
| 3781cc7 | AC-10 | Done | Integration tests: 5 transcripts end-to-end (2026-02-19) |
| c8049ad | Phase A+ word-form + gold standard | Done | Word-form binding, unit disambiguation, expanded to 94 annotations/16 files |

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
- **AC-10**: Integration tests complete (3781cc7, 2026-02-19) ✅

### Phase A+ (Precision Hardening — In Progress)
- [x] **Non-SaaS keyword expansion** (c733aef): TMUS postpaid/prepaid, PYPL debit card, MSFT enterprises/organizations, META magnitude patterns — R=53%→60%
- [x] **Word-form number parsing** (c733aef): "one billion", "two million" etc. — 3 FNs recovered
- [x] **is_percentage_format bug** (c733aef): "1.4 million" no longer misclassified as percentage
- [x] **MIN_PARAGRAPH_CHARS** (c733aef): configurable per pipeline, 30 for transcripts (was 50)
- [x] **PYPL $-prefix transcript bug**: resolved — HuggingFace source transcript has transcription errors ("$224 million" for a count). Gold standard marks these REJECT. Pipeline correctly handles via `v2_currency_on_count_metric`. No code change needed.
- [x] **Q&A section filtering** (6d976c4, cddd2b2): FP filter rules added (bare count threshold, hedging percent, currency-on-count); section type propagation reads `data-section-type` HTML attribute. Transcript converter wraps content in a single `<section data-section-type="prepared_remarks">` — Q&A segments aren't separately tagged in source HTML, so Q&A-specific filtering is limited.
- [x] **Growth-rate percent FPs** (2026-02-28): `_rule_growth_rate_percent` extended — MAU/DAU percent values with growth-verb prefix (e.g., "grew 30%") now blocked without requiring co-occurring absolute count. Fixed ~8 PYPL/META FPs.
- [x] **ARPA/ARPU percent FPs** (2026-02-28): `_rule_arpu_percent` added — PERCENT values for `cm_revenue_per_customer` and `cm_expansion_revenue` blocked (growth rates like "ARPA growth of 4%" are not ARPA values). Fixed ~7 TMUS FPs.
- [x] **CapEx/revenue_concentration FPs** (2026-02-28): `_rule_geographic_revenue` extended to catch CapEx context ("CapEx to be approximately 2% of revenue"). Fixed 1-2 CRM FPs.
- [ ] **Remaining keyword gaps**: ADSK revenue_concentration FNs from Q&A (3 missed), META "almost a billion" value parsing
- Benchmark (94 annotations, 16 files, 2026-02-28): **R=71.8%, P=62.9%, F1=67.0%** — vs prior: R=65.9%, P=38.4%, F1=48.5%
- Target: R≥65% ✓, P≥70% ✗ (7.1pp short), F1≥67% ✓
- Remaining precision gap: ADBE ARR sub-components (~8 FPs), TMUS period disambiguation (~4 FPs), CRM `deals over $1M` keyword pattern (2 FPs — requires SEC gold standard validation before changing)

### Phase B (Expanded Coverage) — COMPLETE (2026-03-01)
- ~~FMP API source~~ (deferred — see note below)
- Company matching by ticker ✅
- Web UI: document type filter, transcript viewer ✅
- Schema migration applied to production DB ✅
- Batch ingestion E2E tested with HuggingFace source (2026-03-01) ✅
  - Fixed field mappings (`symbol` not `ticker`, `content` not `text`)
  - Fixed company upsert (partial unique index on `ticker WHERE NOT NULL`)
  - Fixed persistence: v2_documents.doc_id is UUID; don't pass filing_id as doc_id
  - Added migration 13: transcript section types to v2_segments constraint

> **Note on FMP:** FMP paid API is deferred until Phase C (presentation support) is
> complete and extraction quality is validated on free sources (HuggingFace).
> FMP integration moves to Phase D.

### Phase C (Presentation Support) — COMPLETE (72cd1c6, 5b3b247)
- M1: PDF-to-HTML converter (`presentation_converter.py`) — pdfplumber, page→section, tables, images ✅
- M2: SEC 8-K presentation source (`sec_presentation_source.py`) — EDGAR downloader, idempotent cache ✅
- M3: Section classification (TITLE_SLIDE, KEY_METRICS, FINANCIAL_OVERVIEW, GUIDANCE, APPENDIX) ✅
- M4: FP filter tuning (suppress TITLE_SLIDE/APPENDIX facts, bare integers <1000) ✅
- M5: Gold standard annotations — **DEFERRED** (requires manual PDF annotation)
- M6: Period inference for slide title patterns ("Q4 FY2025 Results", "Full Year 2024") ✅
- Batch ingestor: `scripts/ingest_presentations.py` (--dry-run / --persist) ✅
- DB migration 14: presentation section types added to v2_segments CHECK constraint ✅

### Phase D (Production Readiness)
- FMP API source (`FMPTranscriptSource`) for broader transcript corpus — gated on Phase C
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

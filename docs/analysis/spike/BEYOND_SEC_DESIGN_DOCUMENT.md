# Beyond SEC: Metric Extraction from Earnings Calls & Investor Presentations

## Consolidated Design Document

**Date:** 2026-02-13
**Branch:** `earnings-call-exploration`
**Status:** Research spike complete — GO recommendation

---

## Executive Summary

### Go / No-Go Recommendation: **GO** (conditional)

The V2 extraction pipeline can extract customer metrics from earnings call transcripts **today** with no code changes, achieving **22.1% measured recall** and **63.0% precision** (against 77 manually annotated metrics across 8 transcripts). With targeted adaptations (value binding tuning, period inference patterns, FP filter relaxation, vocabulary expansion), we project **50-58% recall** — meeting the 50% threshold.

| Criterion | Target | Actual (Measured) | Status |
|-----------|--------|-------------------|--------|
| Transcript recall | >= 50% | **22.1%** (current), ~50-58% (projected) | Achievable with changes |
| Presentation recall | >= 40% | Not tested (pending PDF converter) | Deferred |
| Precision (both) | >= 60% | **63.0%** (current) | **Met** |
| Viable data source | At least one free source | HuggingFace: 33K transcripts, MIT license | **Met** |
| Architecture recommendation | Clear with effort estimates | Complete — 22-36 day estimate | **Met** |

### Key Numbers
- 22 earnings call transcripts processed, 100% pipeline success rate
- 79 metric facts extracted (3.6/file average)
- 72ms average processing time per transcript (10x faster than SEC filings)
- Pipeline is ~90% document-agnostic — only configuration changes needed for core stages
- Estimated 22-36 engineering days for full production support

---

## 1. Data Source Recommendation

### Transcripts

| Priority | Source | Cost | Format | Coverage |
|----------|--------|------|--------|----------|
| **Primary** | kurry/sp500_earnings_transcripts (HuggingFace) | Free (MIT) | Structured Parquet | 33K transcripts, 496 companies, 2005-2025 |
| **Secondary** | Financial Modeling Prep API | $149/mo | JSON REST | 8,000+ companies, 10+ year history |
| **Supplementary** | Kaggle Motley Fool dataset | Free | CSV | 18,755 pre-scraped transcripts |

### Presentations

| Priority | Source | Cost | Format | Coverage |
|----------|--------|------|--------|----------|
| **Primary** | SEC EDGAR 8-K exhibits | Free | PDF | Moderate (companies file under Item 7.01/8.01) |
| **Supplementary** | Company IR websites | Free | PDF | Universal but non-standardized |

### Sources Not Recommended
- Seeking Alpha — excellent content but TOS prohibits scraping
- AlphaSense/Capital IQ — cost-prohibitive ($10K+/yr)
- Polygon.io — does not offer transcript data

*Full evaluation: [docs/spike/data_source_evaluation.md](data_source_evaluation.md)*

---

## 2. Format Analysis

### Transcripts vs SEC Filings

| Dimension | SEC S-1/F-1 | Earnings Call |
|-----------|-------------|---------------|
| Structure | Formal sections (ITEM 1, 7, 8) | Speaker turns (Operator → CEO → CFO → Q&A) |
| Tables | Abundant | **None** |
| Charts | Common | **None** |
| Metric format | Table cells + inline text | **Inline text only** |
| Period context | Column headers | Conversational ("fiscal year '25", "this quarter") |
| Value precision | Exact | Often rounded ("about $20M") |
| Length | 50K-200K+ chars | 45K-65K chars |
| Metric density | High (tables concentrate metrics) | Moderate (metrics scattered in remarks) |

### Key Structural Challenges
1. **No tables** — value binding must use text proximity exclusively
2. **Large segments** — a CEO's 5,000-word remarks become one `<p>`, diluting proximity signals
3. **Conversational periods** — "FY'25", "this quarter" don't match formal date patterns
4. **Repetition** — same metric cited 2-3 times across speakers (handled by dedup)

*Full analysis: [docs/spike/format_analysis.md](format_analysis.md)*

---

## 3. POC Results

### Pipeline Performance

| Metric | Value |
|--------|-------|
| Files processed | 22 |
| Pipeline success rate | 100% |
| Total facts extracted | 79 |
| Avg facts per file | 3.6 |
| Avg processing time | 72ms |
| Companies tested | 10 (ADBE, ADSK, CRM, EA, GDDY, INTU, META, MSFT, PYPL, TMUS) |

### Measured Extraction Quality by Company (Annotated Files)

| Company | Ticker | Annotations | TP | FN | FP | Recall | Precision |
|---------|--------|-------------|----|----|-----|--------|-----------|
| Autodesk | ADSK | 3 | 3 | 0 | 2 | **100%** | 60% |
| Salesforce | CRM | 5 | 3 | 2 | 0 | **60%** | 100% |
| GoDaddy | GDDY | 7 | 4 | 3 | 3 | **57%** | 57% |
| Adobe | ADBE | 11 | 4 | 7 | 2 | **36%** | 67% |
| Microsoft | MSFT | 16 | 3 | 13 | 0 | **19%** | 100% |
| Meta | META | 8 | 0 | 8 | 0 | **0%** | — |
| PayPal | PYPL | 13 | 0 | 13 | 3 | **0%** | 0% |
| T-Mobile | TMUS | 14 | 0 | 14 | 0 | **0%** | — |

SaaS companies (ADSK, CRM, GDDY, ADBE) achieve 36-100% recall. Non-SaaS (META, PYPL, TMUS) achieve 0% — vocabulary gaps are the primary cause.

### Stage-by-Stage Bottlenecks

```
Candidates    ████████████████████████  ~230 total (keyword matching works)
     ↓
Bound values  ████████████              ~95 (40% binding rate — BOTTLENECK)
     ↓
Post-FP       ████████                  ~79 (17% filtered — over-aggressive)
     ↓
With period   ███                       ~30 (62% no period — MAJOR GAP)
     ↓
Final facts   ████████                  79 (after dedup)
     ↓
True positives ███                      17 of 77 annotations matched (22.1% recall)
```

*Full results: [docs/spike/poc_results.md](poc_results.md)*

---

## 4. Gap Analysis

### What Works (no changes needed)
- **Ingestion** — HTML parsing is format-agnostic
- **Table reconstruction** — graceful no-op when no tables
- **Candidate generation** — keyword matching works for SaaS vocabulary
- **Fact construction** — format-agnostic
- **Deduplication** — works and is valuable (executives repeat metrics)
- **Validation** — format-agnostic

### What Needs Tuning (config/pattern changes only)
- **Section classification** — add transcript/presentation patterns to `SectionType` enum
- **Period inference** — add patterns for "FY'25", standalone "Q4", document-date fallback
- **Metric keywords** — add industry-specific patterns (telecom, gaming, fintech)

### What Needs Code Changes
- **Value binding** — wider proximity windows + sentence-level awareness for text sources
- **False positive filter** — document-type-aware rule relaxation
- **Pipeline context** — add `document_type` and `document_date` fields

### What Needs New Development
- **Transcript converter** (text → HTML, spike version exists)
- **PDF converter** (for presentations — new development)
- **Document source abstraction** (fetch from HuggingFace, FMP API, EDGAR)

*Full analysis: [docs/spike/gap_analysis.md](gap_analysis.md)*

---

## 5. Architecture Recommendation

### Schema: Extend `filings` table with `document_type`

```sql
ALTER TABLE filings
  ADD COLUMN document_type TEXT NOT NULL DEFAULT 'sec_filing',
  ADD COLUMN document_date DATE,
  ADD COLUMN transcript_source TEXT,
  ALTER COLUMN cik DROP NOT NULL,
  ALTER COLUMN accession_number DROP NOT NULL;
```

### Pipeline: Document-type-aware configuration

```python
# Transcript processing
config = PipelineConfig.for_transcript()
# Sets: enable_image_extraction=False, wider_proximity=True, relaxed_fp=True

pipeline = V2Pipeline(config=config)
result = pipeline.process(
    html_path=transcript_html,
    filing_id=filing_id,
    document_type="earnings_call",
    document_date=date(2025, 2, 26),
)
```

### Document Source Protocol

```python
class DocumentSource(Protocol):
    def fetch(self, identifier: str) -> tuple[Path, DocumentMetadata]: ...
    def list_available(self, company: str) -> list[DocumentMetadata]: ...
```

Implementations: `SECEdgarSource`, `HuggingFaceTranscriptSource`, `FMPTranscriptSource`, `SECPresentationSource`

*Full recommendation: [docs/spike/architecture_recommendation.md](architecture_recommendation.md)*

---

## 6. Implementation Roadmap

### Phase A: Transcript Support (P0) — 2-3 weeks

| Task | Effort | Description |
|------|--------|-------------|
| Pipeline context + config presets | 1-2 days | Add `document_type`, `document_date` to context; create `PipelineConfig.for_transcript()` |
| Value binding tuning | 2-3 days | Wider proximity windows for text, sentence-level binding |
| Period inference patterns | 1-2 days | "FY'25", standalone "Q4", document-date fallback |
| FP filter transcript rules | 1-2 days | Relax segment-level co-occurrence rules for transcripts |
| Transcript converter (production) | 2-3 days | Harden spike converter, split large paragraphs into sentences |
| HuggingFace source | 2-3 days | Implement `DocumentSource` for kurry dataset |
| Schema migration | 1 day | Add columns, relax constraints |
| Integration tests | 2-3 days | End-to-end transcript pipeline tests |
| **Total Phase A** | **~13-19 days** | **Target: >50% recall on transcripts** |

### Phase B: Expanded Coverage — 1-2 weeks

| Task | Effort | Description |
|------|--------|-------------|
| FMP API source | 2-3 days | DocumentSource for non-S&P 500 companies |
| Section classification | 1-2 days | Transcript/presentation SectionType patterns |
| Industry keyword expansion | 1-2 days | Telecom, gaming, fintech vocabulary |
| Company matching | 1 day | Ticker-based matching with CIK fallback |
| Web UI updates | 2-3 days | Document type filter, transcript viewer |
| **Total Phase B** | **~7-11 days** | |

### Phase C: Presentation Support — 2-3 weeks

| Task | Effort | Description |
|------|--------|-------------|
| PDF-to-HTML converter | 5-8 days | pdfplumber for text PDFs; evaluate docling for image PDFs |
| SEC 8-K presentation source | 3-4 days | EFTS search for presentation exhibits |
| Image/chart pipeline tuning | 2-3 days | Presentation chart styles differ from SEC charts |
| Integration tests | 2-3 days | End-to-end presentation pipeline tests |
| **Total Phase C** | **~12-18 days** | **Target: >40% recall on presentations** |

---

## 7. Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| HuggingFace dataset removed or license changed | Low | High | Cache dataset locally; FMP API as backup |
| FMP API price increase or deprecation | Low | Medium | Multiple source strategy; SEC 8-K fallback |
| Transcript language evolution (new metric vocabulary) | Medium | Medium | Regular keyword pattern audits; LLM-assisted pattern discovery |
| PDF converter quality insufficient for presentations | Medium | High | Defer presentations; focus on text PDFs first; evaluate docling |
| False positive rate increase with wider binding | Medium | Medium | Document-type-specific FP rules; human review routing |
| Period inference ambiguity for relative references | High | Medium | Document-date fallback; flag ambiguous periods for review |
| Company matching failures (ticker changes, acquisitions) | Medium | Low | Manual mapping table; SEC EDGAR company lookup |
| Value parsing errors with approximate numbers ("~$20M") | Medium | Low | Add approximate-value pattern to number parser |

---

## 8. Appendix

### A. Sample Extracted Facts (CRM Q4 FY25 Call)

```
Metric: cm_arr
Value: $900,000,000
Raw: "$900 million"
Context: "Data Cloud and AI ARR, it grew 120% year-over-year"
Period: Not inferred (gap)
Confidence: 0.25

Metric: cm_arr
Value: $5,700,000,000
Raw: "$5.7 billion"
Context: "industry business...finished the year at $5.7 billion in ARR"
Period: Not inferred (gap)
Confidence: 0.25

Metric: cm_customers_period_end
Value: 3,000
Raw: "3,000"
Context: "3,000 paying Agentforce customers"
Period: Not inferred (gap)
Confidence: 0.25
```

### B. Pipeline Stage Flow (Transcript)

```
Input: CRM_2025-02-26.html (61KB)
  ↓
Stage 1: Ingestion → 36 segments
  ↓
Stage 2: Section Classification → 36 segments (all COVER)
  ↓
Stage 3: Table Reconstruction → 0 tables
  ↓
Stage 6: Candidate Generation → 5 candidates
  ↓
Stage 7: Value Binding → 7 bound values
  ↓
Stage 7.5: FP Filter → 3 values (4 filtered)
  ↓
Stage 8: Period Inference → 0 periods (3 warnings)
  ↓
Stage 9: Fact Construction → 3 facts
  ↓
Stage 10: Deduplication → 3 facts (0 duplicates)
  ↓
Stage 11: Validation → 3 facts
  ↓
Output: 3 MetricFacts in 77ms
```

### C. Files Created in This Spike

```
docs/spike/
├── BEYOND_SEC_DESIGN_DOCUMENT.md   (this file)
├── data_source_evaluation.md       (Phase 1)
├── format_analysis.md              (Phase 2)
├── poc_results.md                  (Phase 3)
├── gap_analysis.md                 (Phase 4)
└── architecture_recommendation.md  (Phase 5)

scripts/spike/
├── collect_samples.py              (HuggingFace dataset downloader)
├── convert_transcript_to_html.py   (text → HTML converter)
└── run_poc.py                      (pipeline POC runner)

data/spike_samples/
├── inventory.csv                   (20 transcript samples)
├── manual_annotations.csv          (ground truth annotations)
├── transcripts/                    (20 raw text files)
└── transcripts_html/               (22 HTML files for pipeline)

data/spike_results/
└── transcripts_results.csv         (per-file pipeline results)
```

### D. Reproduction Steps

```bash
# 1. Collect transcript samples
python3 scripts/spike/collect_samples.py

# 2. Convert to HTML
python3 scripts/spike/convert_transcript_to_html.py

# 3. Run V2 pipeline POC
python3 scripts/spike/run_poc.py

# Results in: data/spike_results/transcripts_results.csv
```

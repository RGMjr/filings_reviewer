# Architecture Recommendation: Beyond SEC Filings

**Date:** 2026-02-13
**Status:** Complete
**Phase:** 5 of 6

## Key Decisions

### 1. Schema Strategy

**Recommendation: Add `document_type` column to `filings` table + relax constraints**

Rationale:
- The `filings` table already has the right grain (one document per row)
- Adding a `document_type` column (`S-1`, `F-1`, `10-K`, `8-K`, `earnings_call`, `investor_presentation`) covers all document types
- Relax the `check_form_type` constraint to accept new types
- Make `cik` nullable (earnings call transcripts may only have ticker, not CIK)
- Add `ticker` column to `filings` (currently only on `companies`)

Alternatives considered:
- **Parallel `documents` table:** Would duplicate company linkage logic and require changes to every query. Rejected.
- **Generalized `documents` table replacing `filings`:** Too disruptive — would require migrating all existing data. Rejected for initial phase.

**SQL sketch:**
```sql
-- Add to existing filings table
ALTER TABLE filings
  ADD COLUMN document_type TEXT NOT NULL DEFAULT 'sec_filing',
  ADD COLUMN ticker TEXT,
  ADD COLUMN document_date DATE,  -- call date, presentation date
  ADD COLUMN transcript_source TEXT,  -- 'huggingface', 'fmp_api', 'sec_8k'
  ALTER COLUMN cik DROP NOT NULL,
  ALTER COLUMN accession_number DROP NOT NULL,
  ALTER COLUMN sec_html_url DROP NOT NULL;

-- Relax form_type constraint
ALTER TABLE filings DROP CONSTRAINT check_form_type;
ALTER TABLE filings ADD CONSTRAINT check_form_type
  CHECK (form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A', '10-K', '10-K/A',
                        '8-K', 'earnings_call', 'investor_presentation'));
```

**Effort:** Small (migration script + constraint changes)

### 2. Pipeline Changes

**Recommendation: Minimal changes to existing pipeline, new document-type-aware config**

The V2 pipeline architecture is already ~90% document-agnostic. Changes:

| Component | Change Type | Description |
|-----------|-------------|-------------|
| `PipelineContext` | Add fields | `document_type`, `document_date` |
| `PipelineConfig` | Add presets | `PipelineConfig.for_transcript()`, `PipelineConfig.for_presentation()` |
| `SectionClassificationStage` | Config extension | Load transcript/presentation patterns from config |
| `CandidateGenerationStage` | No change | Already generic (reads from YAML) |
| `ValueBindingStage` | Tuning | Wider proximity for `document_type='transcript'` |
| `FalsePositiveFilterStage` | Config | Relaxed rules for `document_type='transcript'` |
| `PeriodInferenceStage` | Pattern additions | Add conversational temporal patterns + document_date fallback |

**No new stages needed.** The existing 12-stage architecture handles transcripts with configuration changes only.

**Effort:** Medium (2-3 days of focused work)

### 3. Document Fetcher Abstraction

**Recommendation: `DocumentSource` Protocol with pluggable implementations**

```python
from typing import Protocol
from pathlib import Path
from dataclasses import dataclass

@dataclass
class DocumentMetadata:
    company_name: str
    ticker: str | None
    cik: str | None
    document_type: str  # 'earnings_call', 'investor_presentation', 'sec_filing'
    document_date: date | None
    source: str  # 'sec_edgar', 'huggingface', 'fmp_api', 'company_ir'
    fiscal_year: int | None = None
    fiscal_period: str = ""

class DocumentSource(Protocol):
    """Protocol for document sources."""

    def fetch(self, identifier: str) -> tuple[Path, DocumentMetadata]:
        """Fetch document and return (html_path, metadata)."""
        ...

    def list_available(self, company: str) -> list[DocumentMetadata]:
        """List available documents for a company."""
        ...
```

**Implementations:**
- `SECEdgarSource` — wraps existing `sec_client.py` + filing fetcher
- `HuggingFaceTranscriptSource` — wraps the kurry dataset
- `FMPTranscriptSource` — wraps FMP API ($149/mo)
- `SECPresentationSource` — fetches 8-K presentation exhibits

**Effort:** Medium (3-5 days, including tests)

### 4. Section Classification

**Recommendation: Per-document-type classifier with shared interface**

Add new `SectionType` enum values:

```python
class SectionType(str, Enum):
    # Existing SEC filing sections
    COVER = "cover"
    RISK_FACTORS = "risk_factors"
    MDA = "mda"
    BUSINESS = "business"
    FINANCIALS = "financials"
    NOTES = "notes"
    EXHIBITS = "exhibits"
    SIGNATURES = "signatures"

    # Transcript sections (new)
    OPERATOR = "operator"
    PREPARED_REMARKS = "prepared_remarks"
    QA_SESSION = "qa_session"

    # Presentation sections (new)
    TITLE_SLIDE = "title_slide"
    KEY_METRICS = "key_metrics"
    BUSINESS_HIGHLIGHTS = "business_highlights"
    FINANCIAL_OVERVIEW = "financial_overview"
    GUIDANCE = "guidance"
    APPENDIX = "appendix"

    OTHER = "other"
    UNKNOWN = "unknown"
```

Use `document_type` to select the appropriate pattern set. The existing `SectionClassificationStage` can dispatch to the right patterns based on the context.

**Effort:** Small (1-2 days)

### 5. Company Matching

**Recommendation: Ticker-based matching with CIK fallback**

Current state:
- `companies` table is keyed on CIK (SEC identifier)
- Transcripts identify companies by ticker (e.g., "ADBE")
- Presentations may use either

Approach:
1. Add `ticker` as a secondary identifier on `companies` table (already has the column, but it's optional)
2. For transcripts: match on ticker first, CIK second
3. For SEC filings: match on CIK first, ticker second
4. For new companies from transcripts: create company record with ticker, add CIK later when SEC filing is found

```sql
-- Make ticker more prominent
CREATE UNIQUE INDEX idx_companies_ticker_unique
  ON companies(ticker) WHERE ticker IS NOT NULL;
```

**Effort:** Small (1 day)

### 6. PDF/PPTX Handling

**Recommendation: Use `pdfplumber` for text-extractable PDFs, `python-pptx` for PPTX, defer image-only PDFs**

Evaluation of options:

| Library | Text PDFs | Image PDFs | PPTX | Tables | Maintenance |
|---------|-----------|------------|------|--------|-------------|
| **pdfplumber** | Excellent | None | None | Good | Active |
| **pymupdf (fitz)** | Excellent | OCR via Tesseract | None | Good | Active |
| **python-pptx** | N/A | N/A | Good | Fair | Active |
| **markitdown** (Microsoft) | Good | Limited | Good | Fair | New (2024) |
| **docling** (IBM) | Good | Good | Good | Good | New (2024) |
| **Unstructured** | Good | Good | Good | Good | Commercial |

**Recommendation for spike → production path:**
1. **Phase 1 (now):** Skip presentations — focus on transcripts (already text)
2. **Phase 2:** Use `pdfplumber` for text-extractable PDFs (most earnings presentations)
3. **Phase 3:** Evaluate `docling` or `markitdown` for image-heavy PDFs — both are open-source, modern, and handle complex layouts. The V2 pipeline's existing OCR/chart stages handle the downstream image processing.

**Effort:** Medium-Large (1-2 weeks for Phase 2+3)

## Architecture Diagram

```
                    ┌─────────────────┐
                    │  DocumentSource  │  (Protocol)
                    │   Protocol       │
                    └──────┬──────────┘
                           │
        ┌──────────┬───────┼──────────┬──────────┐
        ▼          ▼       ▼          ▼          ▼
  ┌──────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
  │SEC Edgar │ │HF Data │ │FMP API │ │8-K PDF │ │IR Site │
  │  Source   │ │Source  │ │Source  │ │Source  │ │Source  │
  └────┬─────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
       │            │          │          │          │
       └────────┬───┘──────────┘──────────┘──────────┘
                │
                ▼
       ┌──────────────┐      ┌──────────────────┐
       │  HTML + Meta  │────▶│  V2 Pipeline      │
       │  (local file) │      │  (config per type) │
       └──────────────┘      └──────┬───────────┘
                                    │
                                    ▼
                            ┌──────────────┐
                            │  MetricFacts  │
                            │  + Evidence   │
                            └──────┬───────┘
                                   │
                                   ▼
                            ┌──────────────┐
                            │  PostgreSQL   │
                            │  (filings +   │
                            │   v2_facts)   │
                            └──────────────┘
```

## Effort Estimates

| Component | T-Shirt | Days | Priority |
|-----------|---------|------|----------|
| Pipeline context + config presets | S | 1-2 | P0 |
| Period inference pattern additions | S | 1-2 | P0 |
| Value binding tuning for transcripts | M | 2-3 | P0 |
| FP filter transcript rules | S | 1-2 | P0 |
| Transcript converter (production) | M | 2-3 | P0 |
| HuggingFace DocumentSource | M | 2-3 | P1 |
| FMP API DocumentSource | M | 2-3 | P1 |
| Schema migration | S | 1 | P1 |
| Section classification patterns | S | 1-2 | P2 |
| Company matching by ticker | S | 1 | P2 |
| PDF converter (presentations) | L | 5-8 | P2 |
| SEC 8-K presentation source | M | 3-4 | P3 |
| **Total** | | **~22-36 days** | |

## Implementation Phases

### Phase A: Transcript Support (P0 + P1) — 2-3 weeks
- Pipeline config presets for transcripts
- Value binding + FP filter + period inference tuning
- HuggingFace document source
- Schema migration
- End-to-end test: run pipeline on 20+ transcripts with >50% recall

### Phase B: Infrastructure (P2) — 1-2 weeks
- Section classification patterns
- Company matching
- FMP API integration
- Web UI updates (document type filter)

### Phase C: Presentations (P2 + P3) — 2-3 weeks
- PDF-to-HTML converter
- SEC 8-K presentation source
- Image/chart pipeline tuning for presentation charts
- End-to-end test: run pipeline on 10+ presentations

### Phase D: Production Readiness — 1 week
- Monitoring and alerting for new document types
- Batch processing scripts for periodic ingestion
- Documentation updates

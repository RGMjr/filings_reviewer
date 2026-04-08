# System Architecture Overview

**Version:** 3.0
**Last Updated:** 2026-04-08
**Status:** Production Ready

---

## Executive Summary

This system extracts structured customer metrics from SEC filings (S-1/F-1, 10-K), earnings call transcripts, and investor presentations at scale to support the Customer Metrics Accounting Standards Board (CMASB) initiative. The system processes thousands of documents using a 13-stage V2 pipeline combining rule-based table reconstruction with selective LLM processing to achieve high quality at minimal cost.

### Key Metrics
- **Target Volume:** 7,304 in-scope S-1/F-1 filings (2015-2025), extensible to 10-K
- **Target Cost:** $500-$1,000 total processing cost
- **Target Quality:** ≥95% metric extraction accuracy
- **Architecture:** 13-stage pipeline with immutable PipelineContext passing through typed stage processors

---

## Purpose and Context

The project's purpose is to:

- Assess how often and how well companies already disclose decision-useful customer metrics in SEC filings
- Demonstrate the need for standardized customer metrics disclosure (CMASB)
- Identify best-practice examples and gaps by industry and over time

Phase 1 focuses on S-1/F-1 registration statements for first-time issuers of public equity. Later phases will extend to 10-K and other filings.

---

## Design Principles

### 1. Analysis-First
Architecture is driven by required analytic outputs (incidence, quality, and metric values) and the data model, not by convenience of extraction.

### 2. Provenance-First
Every metric value, definition, and quality score must be traceable to specific segments in specific filings. No value without provenance.

### 3. Investor-Grade Defensibility
The system must support audit, replication, and quality evaluation for any published statistic.

### 4. Extensibility
Design supports adding:
- New metrics
- New filing types (10-Ks in Phase 2)
- New document types (transcripts, presentations — already supported)
- New industries or cohorts

### 5. Structure-First, LLM-Second
Full table reconstruction with header_path/stub_path binding before LLM calls. Rules and structural parsing handle the majority of extraction; LLM is reserved for unstructured text and image/chart processing.

### 6. Fail Closed
Ambiguous extractions are routed to human review rather than auto-accepted. Low-confidence facts are flagged; the pipeline never guesses.

### 7. Resilience at Scale
- HTML caching (avoid re-downloads)
- Retry logic with exponential backoff
- Error classification (transient vs permanent via `V2TransientError`/`V2FatalError`)
- Checkpointing and progress tracking per filing

---

## High-Level Architecture

### Logical Layers

The system is organized into six logical layers:

1. **Ingestion & Universe Definition**
   - Discover and classify in-scope filings (Phase 1: S-1/F-1 for first-time issuers)
   - Download and persist raw filing documents

2. **Document Structuring & Segmentation**
   - Parse each filing into DOM-native segments (paragraphs, tables, images)
   - Classify sections (MD&A, Risk Factors, Business, etc.)
   - Reconstruct tables with full colspan/rowspan resolution into header_path/stub_path per cell

3. **Candidate Detection & Value Binding**
   - Match segments against YAML metric taxonomy
   - Bind numeric values to metric candidates via structural links
   - Apply false-positive filter rules

4. **Metric Fact Construction**
   - Infer time periods from header context or surrounding text
   - Construct `MetricFact` objects with full evidence packs
   - Extract metric definitions from methodology segments

5. **Quality Assessment & Deduplication**
   - Deduplicate facts by identity tuple (metric + period + unit + scope)
   - Route facts to auto-accept or human review based on confidence thresholds
   - Compute V1-compatible quality scores via `V2QualityScorer`

6. **Orchestration, Monitoring, and Cost Control**
   - Coordinate pipeline runs across filings
   - Track throughput, failures, and LLM cost
   - Support restart, partial re-runs, and incremental improvements

### Component Map

```
┌────────────────────────────────────────────────────────────────────────┐
│                          USER / SCRIPTS                                │
└───────────────────────────────┬────────────────────────────────────────┘
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
   ┌──────────▼─────────┐  ┌───▼────────┐  ┌──────▼──────────┐
   │  UniverseBuilder   │  │  Web UI    │  │  Gold Standard  │
   │  (EDGAR discovery) │  │  (Flask)   │  │  Validation     │
   └──────────┬─────────┘  └───┬────────┘  └─────────────────┘
              │                │
   ┌──────────▼─────────┐      │
   │  FilingFetcher     │      │
   │  (HTML cache)      │      │
   └──────────┬─────────┘      │
              │                │
   ┌──────────▼────────────────▼──────────────────────────────┐
   │                    V2Pipeline                             │
   │                                                           │
   │  Stage 1:  IngestionStage          (lxml parsing)        │
   │  Stage 2:  SectionClassification   (MD&A, Risk, etc.)    │
   │  Stage 3:  TableReconstruction     (header/stub paths)   │
   │  Stage 4:  ImageTriage             (chart vs. deco.)     │
   │  Stage 5:  OCRExtraction           (vision + OCR)        │
   │  Stage 6:  CandidateGeneration     (YAML taxonomy)       │
   │  Stage 7:  ValueBinding            (structural link)     │
   │  Stage 7.5:FalsePositiveFilter     (13 FP rules)         │
   │  Stage 8:  PeriodInference         (header context)      │
   │  Stage 9:  FactConstruction        (MetricFact + pack)   │
   │  Stage 9.5:DefinitionExtraction    (methodology text)    │
   │  Stage 10: Deduplication           (identity tuple)      │
   │  Stage 11: Validation              (review routing)      │
   └──────────┬───────────────────────────────────────────────┘
              │  PipelineResult
              │  (facts, tables, images, segments)
   ┌──────────▼──────────────────────┐
   │  V2PersistenceAdapter           │
   │  (v2_metric_facts, v2_segments, │
   │   v2_tables, v2_image_assets,   │
   │   v2_documents)                 │
   └──────────┬──────────────────────┘
              │
   ┌──────────▼──────────────────────┐
   │  V2QualityScorer                │
   │  (filing_metric_incidence,      │
   │   V1-compatible quality scores) │
   └──────────┬──────────────────────┘
              │
   ┌──────────▼──────────────────────┐
   │  PostgreSQL Database            │
   │  (core + V2 tables)             │
   └─────────────────────────────────┘
```

---

## Core Components

### 1. UniverseBuilder
**Module:** `src/universe/universe_builder.py`
**Purpose:** Discover and classify SEC filings by date range and type
**Input:** Date range, filing type (S-1, F-1, 10-K)
**Output:** Populated `companies` and `filings` tables with classification flags
**Technology:** SEC EDGAR API, BeautifulSoup

**Classification Logic:**
- SPAC detection: three-layer detection (SIC code, EDGAR text, keyword signals)
- First-time issuer: checks for prior equity registrations
- Business type: SaaS, fintech, etc. (conservative "BOTH" signal approach)

### 2. FilingFetcher
**Module:** `src/filing_fetcher/filing_fetcher.py`
**Purpose:** Download and cache filing HTML to avoid re-fetching from SEC
**Input:** Filing metadata (CIK, accession number)
**Output:** `FilingContent` with local HTML path; organized under `data/filings/{cik}/{accession}/`
**Technology:** Filesystem cache, SEC EDGAR HTTP
**Cost:** ~500MB-1GB disk per 1,000 filings

### 3. V2Pipeline
**Module:** `src/extraction_v2/pipeline.py`
**Purpose:** Orchestrate the 13-stage extraction process for a single document
**Input:** HTML path, filing ID, document type
**Output:** `PipelineResult` containing `MetricFact` list, tables, images, segments, and per-stage diagnostics
**Technology:** Python orchestration via `PipelineContext` passed through typed `StageProcessor` instances

**Document type configurations:**
- `PipelineConfig()` — SEC filings (default): strict FP filter, images optional
- `PipelineConfig.for_transcript()` — wider text proximity, relaxed FP filter
- `PipelineConfig.for_presentation()` — image/OCR enabled, short minimum paragraph

**Critical stages (failure aborts pipeline):** Ingestion, TableReconstruction, CandidateGeneration, ValueBinding

### 4. Pipeline Stages

| Stage | Class | Description |
|-------|-------|-------------|
| 1 | `IngestionStage` | lxml HTML parsing into typed `Segment` objects with DOM locators |
| 2 | `SectionClassificationStage` | Assigns section_type (mda, risk_factors, business, financials, etc.) |
| 3 | `TableReconstructionStage` | Resolves colspan/rowspan; computes header_path and stub_path per cell |
| 4 | `ImageTriageStage` | Classifies images as chart, table_image, decorative, logo |
| 5 | `OCRExtractionStage` | Vision API + OCR for labeled chart values; skips unlabeled axes |
| 6 | `CandidateGenerationStage` | Matches segments against `config/metric_keywords.yaml` taxonomy |
| 7 | `ValueBindingStage` | Links numeric values to metric candidates via structural proximity |
| 7.5 | `FalsePositiveFilterStage` | Applies 13 rule-based FP suppression rules |
| 8 | `PeriodInferenceStage` | Extracts period_start/period_end from header_path or surrounding context |
| 9 | `FactConstructionStage` | Constructs `MetricFact` with `EvidencePack` (snippet, header_path, screenshot) |
| 9.5 | `DefinitionExtractionStage` | Extracts metric definitions from methodology/definition segments |
| 10 | `DeduplicationStage` | Merges duplicate facts by (metric, period, unit, scope, cohort) identity tuple |
| 11 | `ValidationStage` | Routes facts to auto_accepted or pending_review based on confidence thresholds |

### 5. V2PersistenceAdapter
**Module:** `src/extraction_v2/persistence.py`
**Purpose:** Write `PipelineResult` to the database idempotently
**Input:** `PipelineResult`, `filing_id`, `DatabaseAdapter`
**Output:** Upserted rows in `v2_metric_facts`, `v2_segments`, `v2_tables`, `v2_table_cells`, `v2_image_assets`, `v2_documents`

### 6. V2QualityScorer
**Module:** `src/extraction_v2/quality_scoring.py`
**Purpose:** Compute V1-compatible quality scores from V2 pipeline outputs
**Input:** `filing_id`, `company_id`, `MetricFact` list, `MetricDefinition` list, `Segment` list
**Output:** `FilingMetricIncidence` rows written to `filing_metric_incidence` (5 scoring dimensions, 0-3 scale)
**Note:** Script-layer only; not a pipeline stage. Runs after persistence.

### 7. OpenAI Client
**Module:** `src/llm/`
**Purpose:** LLM integration for image/chart extraction and definition summarization
**Technology:** OpenAI GPT-4o-mini with PostgreSQL-backed response caching
**Cost:** ~$0.10 per filing average (vision calls are the primary cost driver)

---

## Pipeline Flow

```
UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → V2QualityScorer → Database
```

**Stage 1: Universe Building**
- Queries SEC EDGAR for S-1/F-1 filings (2015-2025)
- Classifies: SPACs, first-time issuers, business types
- Result: 7,304 in-scope filings identified

**Stage 2: Document Retrieval**
- Downloads filing HTML from SEC EDGAR
- Stores in `data/filings/{cik}/{accession}/primary.htm`
- Idempotent: skips already-cached filings

**Stage 3: V2 Extraction (13 stages)**
- Full DOM parsing with XPath locators
- Table reconstruction with colspan/rowspan resolution
- Optional image triage and OCR for chart-heavy filings
- YAML taxonomy matching → value binding → period inference → fact construction
- Deduplication and confidence-based review routing

**Stage 4: Persistence**
- Writes all V2 artifacts to database (idempotent upserts)
- Tracks processing status per filing in `v2_documents`

**Stage 5: Quality Scoring**
- Computes V1-compatible scores for analytics compatibility
- Populates `filing_metric_incidence` with 5-dimension quality assessment

---

## Data Flow: Single Filing Processing

```
Filing Metadata (CIK, accession number, form type)
    │
    ▼
┌───────────────────────────────────┐
│ FilingFetcher                     │
│ data/filings/{cik}/{accession}/   │
│   primary.htm                     │
│ Cache hit: skip download          │
└───────────┬───────────────────────┘
            │ Path to HTML
            ▼
┌───────────────────────────────────┐
│ V2Pipeline.process()              │
│                                   │
│  PipelineContext (mutable)        │
│  ├── segments: list[Segment]      │
│  ├── tables: list[Table]          │
│  ├── images: list[ImageAsset]     │
│  ├── candidates: list[Candidate]  │
│  ├── bound_values: list[...]      │
│  ├── facts: list[MetricFact]      │
│  └── definitions: list[...]       │
│                                   │
│  13 stages execute sequentially   │
└───────────┬───────────────────────┘
            │ PipelineResult
            ▼
┌───────────────────────────────────┐
│ V2PersistenceAdapter              │
│ Upserts: v2_metric_facts,         │
│   v2_segments, v2_tables,         │
│   v2_table_cells, v2_image_assets │
└───────────┬───────────────────────┘
            │
            ▼
┌───────────────────────────────────┐
│ V2QualityScorer                   │
│ Writes: filing_metric_incidence   │
│ (5 quality dimensions, 0-3 scale) │
└───────────────────────────────────┘
```

---

## LLM Usage Strategy

### Models and Roles

- **GPT-4o-mini** (primary):
  - Image classification via vision API (Stage 4-5)
  - OCR text extraction from chart images (Stage 5)
  - Definition/methodology summarization (Stage 9.5)
  - PostgreSQL-backed caching by `(filing_id, source_segment_id, task_type)`
  - Cost: $0.15/M input tokens, $0.60/M output tokens

- **Future:** GPT-4o for complex edge cases (currently unused)

### Cost Control Mechanisms

- Full table reconstruction handles structured data at $0 LLM cost
- Images skipped unless relevance score exceeds `min_image_relevance` threshold
- `max_llm_calls_per_document` hard cap (default: 100)
- LLM responses cached by content hash — re-runs cost nothing
- Image and chart extraction disabled automatically if `OPENAI_API_KEY` is unset

### Reliability

- Structured JSON schemas for all LLM extraction calls
- `V2TransientError` propagated for caller retry (network/API timeouts)
- `V2FatalError` aborts pipeline cleanly for non-recoverable failures
- Pipeline continues past non-critical stage failures

---

## Scalability and Performance

### Parallelism Model

- **Filing-level parallelism:** Process different filings concurrently in separate workers
- Each worker runs the full 13-stage pipeline for its assigned filings
- Database writes use short transactions with upsert semantics

### Database Considerations

- PostgreSQL as primary store
- V2 tables use UUID primary keys; core tables use BIGSERIAL
- Key indices on `v2_metric_facts(doc_id)`, `(canonical_metric_id)`, `(review_status)`, `(confidence)`
- GIN indices on `evidence_pack` and `source_locator` JSONB columns
- Identity index on `(canonical_metric_id, period_start, period_end, unit, scope, cohort_def)` for deduplication

### Long-Running Operations

- Runs are **restartable**: `v2_documents.status` tracks per-filing state
- All components are idempotent at the filing level (upserts)
- Processing statuses: `pending`, `parsing`, `extracting`, `reviewing`, `complete`, `failed`

---

## Technology Stack

### Core Languages & Frameworks
- **Python 3.11+** (primary language)
- **PostgreSQL** (database via psycopg3)
- **OpenAI Python SDK** (LLM and vision integration)
- **Flask** (web UI)

### Key Libraries

| Library | Purpose | Version |
|---------|---------|---------|
| `lxml` | Fast HTML/XML parsing (primary parser in V2) | ≥5.0.0 |
| `requests` | HTTP requests to SEC | ≥2.31.0 |
| `beautifulsoup4` | HTML parsing (supplementary) | ≥4.12.0 |
| `pandas` | Data manipulation | ≥2.0.0 |
| `openai` | GPT / vision API client | ≥1.0.0 |
| `python-dotenv` | Environment config | ≥1.0.0 |
| `psycopg[binary]` | PostgreSQL adapter | ≥3.1.0 |
| `pytest` | Testing framework | ≥7.4.0 |
| `black` | Code formatting | ≥23.0.0 |
| `ruff` | Linting | ≥0.1.0 |

---

## Database Schema

### Core Tables (sql/01-08)

| Table | Purpose |
|-------|---------|
| `companies` | One row per issuer; CIK, name, ticker, industry |
| `filings` | One row per SEC filing; classification flags, processing status |
| `source_segments` | V1/legacy segment storage; still referenced by review tools |
| `metric_values` | V1/legacy extracted values |
| `metric_definitions` | V1/legacy extracted definitions |
| `filing_metric_incidence` | Quality scores (0-3 per dimension); written by `V2QualityScorer` |
| `review_candidates` | Human review queue |
| `review_decisions` | Completed human review decisions |
| `metrics` | Canonical metric registry (metric_id, display_name, etc.) |

### V2 Tables (sql/09_v2_schema.sql)

| Table | Purpose |
|-------|---------|
| `v2_metric_facts` | Primary extraction output; one row per extracted value with full provenance |
| `v2_segments` | DOM-native content blocks with section classification and XPath locators |
| `v2_tables` | Reconstructed tables with row/col counts and section context |
| `v2_table_cells` | Individual cells with header_path[] and stub_path[] arrays |
| `v2_image_assets` | Extracted images with classification, OCR text, and chart data |
| `v2_documents` | Filing-level processing metadata and status |
| `v2_review_decisions` | Human review decisions linked to V2 facts |

### Key V2 Fact Columns

`v2_metric_facts` stores each extracted value with:
- `value` / `value_raw` / `unit` / `currency` — the extracted number
- `period_type` / `period_start` / `period_end` — time dimension
- `scope` / `scope_detail` / `cohort_def` / `customer_type` — breakdown dimensions
- `source_type` — `html_table`, `ocr_table`, `text`, or `chart`
- `source_locator` (JSONB) — XPath, segment ID, cell position
- `evidence_pack` (JSONB) — snippet HTML, header_path, stub_path, context windows, screenshot path
- `confidence` / `requires_review` / `review_status` — quality routing signals

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| UniverseBuilder | Complete | 7,304 in-scope S-1/F-1 filings identified |
| FilingFetcher | Complete | Filesystem cache; SEC rate-limiting compliant |
| IngestionStage | Complete | lxml-based; XPath locators for all segments |
| SectionClassificationStage | Complete | MD&A, Risk Factors, Business, Financials, etc. |
| TableReconstructionStage | Complete | Full colspan/rowspan resolution; header_path/stub_path |
| ImageTriageStage | Complete | chart, table_image, decorative, logo classification |
| OCRExtractionStage | Complete | Vision API + OCR; labeled values only |
| CandidateGenerationStage | Complete | YAML taxonomy matching (`config/metric_keywords.yaml`) |
| ValueBindingStage | Complete | Structural binding; 1,436 lines |
| FalsePositiveFilterStage | Complete | 13 FP suppression rules; 1,538 lines |
| PeriodInferenceStage | Complete | Header context + fallback; 1,246 lines |
| FactConstructionStage | Complete | MetricFact + EvidencePack |
| DefinitionExtractionStage | Complete | Methodology and definition segments |
| DeduplicationStage | Complete | Identity-tuple deduplication |
| ValidationStage | Complete | Confidence-based review routing |
| V2PersistenceAdapter | Complete | Idempotent upserts to all V2 tables |
| V2QualityScorer | Complete | 5-dimension quality scores; writes filing_metric_incidence |
| OpenAI Client (llm/) | Complete | PostgreSQL-backed LLM response cache |
| Web UI (Flask) | Complete | Human review interface |
| **Overall** | **Production Ready** | V2 is sole production pipeline |

> **Note:** V1 extraction code (`src/extraction/`) is retained for historical reference only. It is not used in any production pipeline.

---

## Key Design Decisions

### 1. Structure-First, LLM-Second
Full table reconstruction via colspan/rowspan resolution enables exact value-to-header binding without any LLM calls for structured data.

### 2. Provenance Non-Negotiable
Every `MetricFact` carries a `source_locator` (XPath + cell position) and `evidence_pack` (rendered snippet + header_path). The system cannot produce a fact without a traceable source.

### 3. Fail Closed
Ambiguous facts route to `pending_review` rather than `auto_accepted`. Auto-accept requires confidence ≥ 0.90. Auto-reject applies below 0.15.

### 4. Idempotent Operations
All pipeline stages and persistence operations are safe to re-run. `v2_documents.status` enables precise resumption.

### 5. Conservative False-Positive Filtering
Stage 7.5 applies 13 structural and contextual rules to suppress non-metric values before fact construction, reducing review queue burden.

### 6. Multi-Document-Type Support
`PipelineConfig` has factory methods for SEC filings, transcripts, and presentations. Document-type-specific parameters (proximity windows, FP filter strictness, image settings) are isolated to config, not stage logic.

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM cost overruns | High | PostgreSQL cache, GPT-4o-mini preference, `max_llm_calls_per_document` cap |
| LLM rate limits | Medium | `V2TransientError` propagation for caller retry with exponential backoff |
| SEC blocking/throttling | Medium | HTML caching, polite delays, SEC User-Agent header |
| Low extraction quality | High | Structure-first binding, FP filter, evidence pack for audit, human review queue |
| System crashes | Medium | Idempotent stages, `v2_documents.status` checkpointing |
| HTML parsing failures | Low | `V2FatalError` on critical stage failure; non-critical stages continue |
| Metric definition drift | Medium | Versioned YAML taxonomy (`config/metric_keywords.yaml`) |

---

## Getting Started

```bash
# 1. Install dependencies
uv pip install -r requirements.txt

# 2. Configure environment
cp .env.template .env
# Set DATABASE_URL and SEC_USER_AGENT in .env

# 3. Apply database migrations
psql $DATABASE_URL -f sql/01_create_schema.sql
# ... apply remaining migrations in order

# 4. Run tests
pytest -v

# 5. Build universe (discover filings)
python3 scripts/build_universe.py --start 2015-01-01 --end 2025-12-31

# 6. Fetch filing HTML
python3 scripts/fetch_filings.py

# 7. Run V2 extraction
python3 scripts/run_v2_extraction.py
```

---

## Scale & Scope

- **In-scope universe:** 7,304 S-1/F-1 filings (2015-2025), first-time issuers only
- **Excluded:** SPACs, secondary-only offerings, investment vehicles, resource extraction
- **Phase 2 target:** 10-K filings (same schema; `form_type = '10-K'`)
- **Cost profile:** Predominantly $0 for table extraction; ~$0.10/filing average for image/text LLM calls
- **Disk:** ~500MB-1GB per 1,000 filings for HTML cache

---

## Related Documentation

- **Data Model:** `docs/architecture/data-model.md` - Database schemas, relationships
- **Extraction Details:** `docs/architecture/extraction-pipeline.md` - V2 stage interfaces and extraction logic
- **LLM Integration:** `docs/architecture/llm-integration.md` - OpenAI integration, prompts, costs
- **Requirements:** `docs/requirements/analytic-requirements.md` - Business requirements
- **Quality Model:** `docs/development/quality-model.md` - QA scoring framework
- **Testing:** `docs/development/testing.md` - Test strategy
- **Documentation Index:** `docs/README.md`

---

**Last Updated:** 2026-04-08
**Version:** 3.0
**Status:** Production Ready

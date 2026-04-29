# System Architecture Overview

**Version:** 3.1
**Last Updated:** 2026-04-25
**Status:** Production Ready (presence-pivot mid-rollout)

---

> **Pivot status (2026-04-25):** The system's primary scoring surface is **presence** — per-`(doc_id, canonical_metric_id)` records aggregated from text facts, chart detections, the Vision metric-classifier, and metric definitions, persisted to `v2_text_metric_presence`. Per-value `MetricFact` rows continue as advisory evidence; CMASB-required values flow via manual entry (`POST /api/v2/missed-metric`). Chart-presence pivot is **live** (#86, 2026-04-23). Text-presence PR1 **landed** (#182, 2026-04-16). PR2–PR5 pending. See [`../operations/text-pipeline-presence-pivot-plan.md`](../operations/text-pipeline-presence-pivot-plan.md).

## Executive Summary

This system extracts **metric presence** (with advisory values where available) from SEC filings (S-1/F-1, 10-K), earnings call transcripts, and investor presentations at scale to support the Customer Metrics Accounting Standards Board (CMASB) initiative. The system processes thousands of documents through an up-to-16-stage V2 pipeline that combines rule-based table reconstruction, selective LLM processing, and a final `MetricPresenceStage` that aggregates signals into per-(filing, metric) presence rows with full provenance.

### Key Metrics
- **Target Volume:** 7,304 in-scope S-1/F-1 filings (2015-2025), extensible to 10-K
- **Target Cost:** $500-$1,000 total processing cost
- **Target Quality:** **presence-F1** is primary (Tier 1 must-not-miss); value-correctness on text/table sources remains a secondary advisory metric
- **Architecture:** Up to 16-stage pipeline (image stages and `IMAGE_CLASSIFY` are conditional) with `PipelineContext` passing through typed stage processors; final `MetricPresenceStage` aggregates signals into `v2_text_metric_presence` rows

---

## Purpose and Context

The project's purpose is to:

- Assess how often and how well companies already disclose decision-useful customer metrics in SEC filings
- Demonstrate the need for standardized customer metrics disclosure (CMASB)
- Identify best-practice examples and gaps by industry and over time

Phase 1 focuses on S-1/F-1 registration statements for first-time issuers of public equity. Later phases will extend to 10-K and other filings.

---

## Design Principles

### 1. Analysis-First (presence as the unit of analysis)
Architecture is driven by required analytic outputs — primarily **per-(filing, metric) presence** — and the data model, not by convenience of extraction. Per-value extraction is retained as advisory evidence and as the substrate for definition/methodology assessment, but presence is the headline output.

### 2. Provenance-First
Every presence row, metric value, definition, and quality score must be traceable to specific segments or images in specific filings. Presence rows carry `evidence_segment_ids` + `advisory_fact_ids` (JSONB pointers, non-FK) back to source. Every advisory `MetricFact` carries a complete `EvidencePack`. No claim without provenance.

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

5. **Deduplication & Routing**
   - Deduplicate facts by identity tuple (metric + period + unit + scope)
   - Route facts to auto-accept or human review based on confidence thresholds

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
**Purpose:** Orchestrate the up-to-16-stage extraction process (image stages 4–5b and IMAGE_CLASSIFY are conditional) for a single document, ending in `MetricPresenceStage`
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
| 4 | `ImageTriageStage` | Classifies images as chart, table_image, decorative, logo (conditional) |
| 5 | `OCRExtractionStage` | Vision API + OCR for labeled chart values; skips unlabeled axes (conditional) |
| 5a | `ChartFactBridgeStage` | Rule-based `ChartMetricClassifier` writes `(metric_id, score)` pairs to `v2_image_assets.detected_metrics` — **presence-only**, no per-value chart facts (conditional) |
| 5b | `ImageClassifyStage` | Vision API metric classifier; appends to `v2_image_classifications` audit trail (gated by `ENABLE_METRIC_CLASSIFY`) |
| 6 | `CandidateGenerationStage` | Matches segments against `config/metric_keywords.yaml` taxonomy |
| 7 | `ValueBindingStage` | Links numeric values to metric candidates via structural proximity |
| 7.5 | `FalsePositiveFilterStage` | Applies 13 rule-based FP suppression rules |
| 8 | `PeriodInferenceStage` | Extracts period_start/period_end from header_path or surrounding context |
| 9 | `FactConstructionStage` | Constructs `MetricFact` with `EvidencePack` (snippet, header_path, screenshot) |
| 9.5 | `DefinitionExtractionStage` | Extracts metric definitions from methodology/definition segments |
| 10 | `DeduplicationStage` | Merges duplicate facts by (metric, period, unit, scope, cohort) identity tuple |
| 11 | `ValidationStage` | Routes facts to auto_accepted or pending_review based on confidence thresholds |
| 12 | `MetricPresenceStage` | **Final stage / primary scoring surface.** Aggregates dedup'd facts, chart `detected_metrics`, and definitions into `MetricPresence` rows (one per `(doc_id, canonical_metric_id)`); upserted to `v2_text_metric_presence` with `evidence_segment_ids` and `advisory_fact_ids` provenance |

### 5. V2PersistenceAdapter
**Module:** `src/extraction_v2/persistence.py`
**Purpose:** Write `PipelineResult` to the database idempotently
**Input:** `PipelineResult`, `filing_id`, `DatabaseAdapter`
**Output:** Upserted rows in `v2_metric_facts`, `v2_segments`, `v2_tables`, `v2_table_cells`, `v2_image_assets`, `v2_documents`

### 6. OpenAI Client
**Module:** `src/llm/`
**Purpose:** LLM integration for image/chart extraction and definition summarization
**Technology:** OpenAI GPT-4o-mini with PostgreSQL-backed response caching
**Cost:** ~$0.10 per filing average (vision calls are the primary cost driver)

---

## Pipeline Flow

```
UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → Database
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

---

## Provenance: Reverse-Trace from Presence to Source

A researcher receives a presence claim (`doc_id=42, canonical_metric_id='cm_net_revenue_retention', score=0.92`) and needs to walk it back to source evidence. The reverse-trace is one of the system's hard requirements — every presence row must be auditable.

**Step 1 — read presence + provenance pointers:**

```sql
SELECT score, detected_at_stage, evidence_segment_ids,
       advisory_fact_ids, advisory_value_count
FROM v2_text_metric_presence
WHERE doc_id = 42 AND canonical_metric_id = 'cm_net_revenue_retention';
```

**Step 2a — for text/table evidence, walk segment IDs back to source text:**

```sql
SELECT s.segment_id, s.section_type, s.dom_locator, s.segment_text
FROM v2_segments s
WHERE s.segment_id = ANY (
    SELECT (jsonb_array_elements_text(p.evidence_segment_ids))::uuid
    FROM v2_text_metric_presence p
    WHERE p.doc_id = 42 AND p.canonical_metric_id = 'cm_net_revenue_retention'
);
```

**Step 2b — for advisory fact IDs, read the EvidencePack:**

```sql
SELECT f.fact_id, f.value, f.unit, f.period_start, f.period_end,
       f.source_type, f.evidence_pack
FROM v2_metric_facts f
WHERE f.fact_id = ANY (
    SELECT (jsonb_array_elements_text(p.advisory_fact_ids))::uuid
    FROM v2_text_metric_presence p
    WHERE p.doc_id = 42 AND p.canonical_metric_id = 'cm_net_revenue_retention'
);
```

**Step 3 — for chart-only presence (empty `evidence_segment_ids`), pivot to image confirmations:**

```sql
SELECT ia.img_id, ia.dom_locator, ia.detected_metrics,
       imc.decision, imc.reviewer_id, imc.created_at
FROM v2_image_assets ia
LEFT JOIN v2_image_metric_confirmations imc
    ON imc.img_id = ia.img_id
   AND COALESCE(imc.confirmed_metric_id, imc.detected_metric_id)
       = 'cm_net_revenue_retention'
WHERE ia.doc_id = 42
  AND ia.detected_metrics @> '[{"metric_id":"cm_net_revenue_retention"}]'::jsonb;
```

**Step 4 — for the Vision-classifier audit trail (independent signal), join `v2_image_classifications`:**

```sql
SELECT ic.img_id, ic.predicted_metrics, ic.cost_usd, ic.created_at
FROM v2_image_classifications ic
JOIN v2_image_assets ia USING (img_id)
WHERE ia.doc_id = 42
  AND ic.predicted_metrics @> '[{"metric_id":"cm_net_revenue_retention"}]'::jsonb;
```

**Important:** `evidence_segment_ids` and `advisory_fact_ids` are JSONB arrays, **not** foreign keys. A presence row can outlive the fact rows it cites — e.g., when `force=True` re-extraction recreates facts with new UUIDs. That's intentional: presence is a doc-level claim independent of which specific fact rows currently back it. The `v2_audit_log` table records batch-level changes; presence-row history is captured in `updated_at` only.

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
└───────────────────────────────────┘
```

---

## LLM Usage Strategy

### Models and Roles

- **GPT-4o-mini** (text):
  - Cost: $0.15/M input tokens, $0.60/M output tokens
  - Used for any explicit text-extraction prompts via `OpenAIClient` (definition extraction is rule-based in V2 — no LLM)
  - PostgreSQL-backed caching via `LLMCache`

- **GPT-4o** (vision):
  - Stage 5 — `OCRExtractionStage` / `VisionClient`: OCR + labeled chart-value extraction (one call per processed image)
  - Stage 5b — `ImageClassifyStage`: Vision metric-classifier; appends to `v2_image_classifications` audit trail. Gated by `ENABLE_METRIC_CLASSIFY` env var. **No `MetricFact` rows emitted** — output is a presence signal consumed by `MetricPresenceStage` and reviewer UI.

Stage 5a `ChartFactBridgeStage` and `MetricPresenceStage` are **rule-based, no LLM** — they post-process Vision/text outputs into presence signals and aggregated presence rows respectively.

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
- Each worker runs the full up-to-16-stage pipeline (ending in `MetricPresenceStage`) for its assigned filings
- Database writes use short transactions with upsert semantics

### Database Considerations

- PostgreSQL as primary store
- V2 tables use UUID primary keys; core tables use BIGSERIAL
- Key indices on `v2_metric_facts(filing_id)`, `(canonical_metric_id)`, `(review_status)`, `(confidence)`
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

### Core Tables (sql/01, sql/04)

| Table | Purpose |
|-------|---------|
| `companies` | One row per issuer; CIK, name, ticker, industry |
| `filings` | One row per SEC filing; classification flags, processing status |
| `metrics` | Canonical metric registry (metric_id, display_name, etc.) |

### V2 Tables (sql/09_v2_schema.sql, sql/29, sql/31, sql/42–47)

| Table | Purpose |
|-------|---------|
| `v2_text_metric_presence` (sql/46) | **Primary scoring surface.** One row per `(doc_id, canonical_metric_id)`; `score`, `detected_at_stage`, `evidence_segment_ids` (JSONB), `advisory_fact_ids` (JSONB), `advisory_value_count`. Upserted by `MetricPresenceStage`. |
| `v2_image_metric_confirmations` (sql/43, sql/47) | Reviewer adjudications of image-presence detections (accept / reject / correct / add / skip). Replaces the per-value chart-fact review path. |
| `v2_image_classifications` (sql/45) | Append-only audit trail for the Vision-API metric-classifier (Stage 5b, gated by `ENABLE_METRIC_CLASSIFY`). |
| `v2_metric_facts` | Advisory per-value extraction output; one row per extracted value with full provenance. Chart sources do not auto-emit new rows post-#86. |
| `v2_metric_definitions` | Issuer-specific definition and methodology text, one per `(doc_id, canonical_metric_id)`. |
| `v2_segments` | DOM-native content blocks with section classification and XPath locators |
| `v2_tables` | Reconstructed tables with row/col counts and section context |
| `v2_table_cells` | Individual cells with header_path[] and stub_path[] arrays |
| `v2_image_assets` | Extracted images with classification, OCR text, chart data, and `detected_metrics` JSONB (sql/42, presence pairs from rule-based classifier) |
| `v2_documents` | Filing-level processing metadata and status |
| `v2_review_decisions` | Human review decisions linked to V2 facts |
| `v2_image_review_decisions` | Legacy per-image review decisions (read-only; superseded by `v2_image_metric_confirmations`) |
| `v2_audit_log` | HTTP audit trail for V2 review routes (replaces V1 `review_audit_log`) |

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
| ChartFactBridgeStage (Stage 5a) | Complete | Rule-based presence pairs to `v2_image_assets.detected_metrics`; no per-value chart facts |
| ImageClassifyStage (Stage 5b) | Live (gated by `ENABLE_METRIC_CLASSIFY`) | Vision metric-classifier; audit trail in `v2_image_classifications` |
| CandidateGenerationStage | Complete | YAML taxonomy matching (`config/metric_keywords.yaml`) |
| ValueBindingStage | Complete | Structural binding; 1,436 lines |
| FalsePositiveFilterStage | Complete | 13 FP suppression rules; 1,538 lines |
| PeriodInferenceStage | Complete | Header context + fallback; 1,246 lines |
| FactConstructionStage | Complete | MetricFact + EvidencePack |
| DefinitionExtractionStage | Complete | Methodology and definition segments |
| DeduplicationStage | Complete | Identity-tuple deduplication |
| ValidationStage | Complete | Confidence-based review routing |
| **MetricPresenceStage (final)** | **PR1 landed (#182)** | Aggregates facts/charts/definitions into `v2_text_metric_presence`; primary scoring surface (PR2 flips Tier-1 gate to presence-F1) |
| V2PersistenceAdapter | Complete | Idempotent upserts to all V2 tables; `presence_only=True` skips fact write |
| OpenAI Client (llm/) | Complete | PostgreSQL-backed LLM response cache |
| Web UI (Flask) | Complete | Human review interface |
| **Overall** | **Production Ready** | V2 is sole production pipeline |

> **Note:** The `src/extraction/` package has been deleted from the codebase. See `docs/architecture/extraction-pipeline.md` for the current V2 extraction architecture.

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

- **Pivot Plan (authoritative for in-flight rollout):** `docs/operations/text-pipeline-presence-pivot-plan.md`
- **Data Model:** `docs/architecture/data-model.md` - Database schemas, relationships, presence tables
- **Extraction Details:** `docs/architecture/extraction-pipeline.md` - V2 stage interfaces, MetricPresenceStage
- **LLM Integration:** `docs/architecture/llm-integration.md` - OpenAI + Vision metric-classifier
- **Requirements:** `docs/requirements/analytic-requirements.md` - Business requirements
- **Quality Model:** `docs/development/quality-model.md` - presence-F1 primary; value-correctness advisory
- **Testing:** `docs/development/testing.md` - Test strategy
- **Documentation Index:** `docs/README.md`

---

**Last Updated:** 2026-04-25
**Version:** 3.1
**Status:** Production Ready (presence-pivot mid-rollout)

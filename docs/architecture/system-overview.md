# System Architecture Overview

**Version:** 2.3
**Last Updated:** 2026-01-07
**Status:** Production Ready

---

## Executive Summary

This system extracts structured customer metrics from SEC filings (S-1/F-1, 10-K) at scale to support the Customer Metrics Accounting Standards Board (CMASB) initiative. The system processes thousands of filings using a hybrid approach combining rule-based table extraction with selective LLM processing to achieve 95% cost reduction while maintaining high quality.

### Key Metrics
- **Target Volume:** 7,304 in-scope S-1/F-1 filings (2015-2025), extensible to 10-K
- **Target Cost:** $500-$1,000 total processing cost
- **Target Quality:** ≥95% metric extraction accuracy
- **Architecture:** Modular pipeline with pure functions and stateless processing

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
Every metric value, definition, and quality score must be traceable to specific segments in specific filings.

### 3. Investor-Grade Defensibility
The system must support audit, replication, and quality evaluation for any published statistic.

### 4. Extensibility
Design supports adding:
- New metrics
- New filing types (10-Ks in Phase 2)
- New industries or cohorts

### 5. Cost-Aware LLM Usage
Minimize token spend with:
- Rules and simple classifiers first
- Targeted, small-context LLM calls
- Clear fallbacks and retry rules

### 6. Separation of Concerns
```
Discovery → Caching → Processing → QA → Storage
    ↓          ↓          ↓        ↓       ↓
  Clean    Clean      Clean    Clean   Clean
Interface Interface Interface Interface Interface
```

### 7. Resilience at Scale
- HTML caching (avoid re-downloads)
- Retry logic with exponential backoff
- Error classification (transient vs permanent)
- Checkpointing and progress tracking

---

## High-Level Architecture

### Logical Layers

The system is organized into six logical layers:

1. **Ingestion & Universe Definition**
   - Discover and classify in-scope filings (Phase 1: S-1/F-1 for first-time issuers)
   - Download and persist raw filing documents

2. **Document Structuring & Segmentation**
   - Parse each filing into structured sections and segments (paragraphs, tables, footnotes)
   - Populate `source_segments` table

3. **Candidate Detection**
   - Identify segments likely to contain customer metrics, definitions, or methodologies
   - Use keyword rules and lightweight LLM classification

4. **Metric Extraction**
   - From candidate segments, extract:
     - Numeric metric values (`metric_values`)
     - Definitions and methodologies (`metric_definitions`)
   - Preserve full provenance to `source_segments`

5. **Quality Assessment (QA)**
   - Apply rule-based checks and LLM scoring
   - Populate `filing_metric_incidence` and QA fields in fact tables

6. **Orchestration, Monitoring, and Cost Control**
   - Coordinate pipeline runs across filings
   - Track throughput, failures, and LLM cost
   - Support restart, partial re-runs, and incremental improvements

### Component Map

```
┌──────────────────────────────────────────────────────────────────┐
│                     USER INTERACTION                             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                ┌───────────▼───────────┐
                │   CLI Interface       │
                │   (main.py)          │
                └───────────┬───────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼────────┐  ┌──────▼──────┐  ┌────────▼────────┐
│   Discovery    │  │ Orchestrator │  │   Monitoring    │
│   Service      │  │              │  │   Dashboard     │
└───────┬────────┘  └──────┬───────┘  └─────────────────┘
        │                  │
        │          ┌───────▼────────┐
        │          │  Batch Queue   │
        │          │  (parallel)    │
        │          └───────┬────────┘
        │                  │
        │          ┌───────▼─────────────────────────────┐
        │          │   Stateless Processing Agent        │
        │          │   ┌──────────────────────────────┐  │
        │          │   │ 1. Cache Layer (HTML)        │  │
        └──────────┼───►                              │  │
                   │   │ 2. Segmenter (HTML parsing)  │  │
                   │   │                              │  │
                   │   │ 3. Metric Classifier         │  │
                   │   │                              │  │
                   │   │ 4. Value Extractor           │  │
                   │   │    (tables + LLM)            │  │
                   │   │                              │  │
                   │   │ 5. Definition Extractor      │  │
                   │   │    (LLM-enhanced)            │  │
                   │   │                              │  │
                   │   │ 6. Quality Scorer            │  │
                   │   └──────────────────────────────┘  │
                   └───────────┬──────────────────────────┘
                               │
                   ┌───────────▼────────────┐
                   │   Storage Layer        │
                   │   ┌─────────────────┐  │
                   │   │ PostgreSQL DB   │  │
                   │   │  - companies    │  │
                   │   │  - filings      │  │
                   │   │  - segments     │  │
                   │   │  - metrics      │  │
                   │   │  - values       │  │
                   │   │  - definitions  │  │
                   │   │  - incidence    │  │
                   │   │  - review_cands │  │
                   │   │  - suppressed   │  │
                   │   └─────────────────┘  │
                   └────────────────────────┘
```

---

## Core Components

### 1. Universe Builder
**Purpose:** Discover and classify SEC filings by date range and type
**Input:** Date range, filing type (S-1, F-1, 10-K)
**Output:** Populated `companies` and `filings` tables with classification flags
**Technology:** SEC EDGAR API, BeautifulSoup
**Status:** Complete (93% test coverage)

**Classification Logic:**
- SPAC detection: keyword-based signals
- First-time issuer: checks for prior equity registrations
- Business type: SaaS, fintech, etc. (conservative "BOTH" signal approach)

### 2. Filing Fetcher
**Purpose:** Download and cache filing HTML to avoid re-fetching from SEC
**Input:** Filing ID (CIK-AccessionNumber)
**Output:** HTML content (from cache or fresh download)
**Technology:** Filesystem cache
**Cost:** ~500MB-1GB disk per 1,000 filings
**Status:** Complete (94% test coverage)

### 3. HTML Segmenter
**Purpose:** Split HTML into sections, paragraphs, tables, footnotes
**Input:** HTML content, filing metadata
**Output:** `source_segments` table rows
**Technology:** BeautifulSoup + regex patterns
**Status:** Complete (80% test coverage)

### 4. Metric Classifier
**Purpose:** Identify segments containing metrics, definitions, methodologies
**Input:** `source_segments`
**Output:** Updated segments with classification flags
**Technology:** Keyword matching + optional LLM
**Status:** Complete (98% test coverage)

### 4.5. Structure Parser
**Purpose:** Parse table row structure to prevent cross-row keyword matches
**Input:** HTML table segments
**Output:** Structured row data with cell boundaries
**Technology:** BeautifulSoup HTML parsing
**Status:** Complete (97% test coverage)

### 4.6. Candidate Detector
**Purpose:** Unified detection of metric candidates across segment types
**Input:** Classified segments
**Output:** Candidate matches with positions and confidence
**Technology:** Rule-based pattern matching with context awareness
**Status:** Complete (97% test coverage)

### 4.7. Context Extractor
**Purpose:** Extract surrounding context for metric values
**Input:** Segment text with value positions
**Output:** Context windows around detected values
**Technology:** Text analysis and window extraction
**Status:** Complete

### 5. Value Extractor
**Purpose:** Extract numeric values from tables and text
**Input:** Classified segments
**Output:** `metric_values` table rows
**Technology:** Rule-based (tables) + LLM (GPT-4o-mini for text)
**Status:** Complete (66% test coverage)

### 6. Definition Extractor
**Purpose:** Extract metric definitions and calculation methodologies
**Input:** Definition/methodology segments
**Output:** `metric_definitions` table rows
**Technology:** LLM-enhanced extraction with quote verification
**Status:** Complete (89% test coverage)

### 6.5. Cohort Chart Detector
**Purpose:** Identify cohort analysis charts and visualizations
**Input:** Filing HTML content
**Output:** Cohort chart candidates with confidence scores
**Technology:** HTML parsing with keyword proximity detection
**Status:** Complete (21 tests covering detection and scoring)

### 7. Quality Scorer
**Purpose:** Assess disclosure quality on 0-3 scale
**Input:** All extracted data for a filing-metric pair
**Output:** `filing_metric_incidence` table rows
**Technology:** Rule-based quality rubrics
**Status:** Complete (100% test coverage)

### 8. Extraction Pipeline
**Purpose:** Orchestrate full extraction flow
**Input:** Filing ID
**Output:** All tables populated for that filing
**Technology:** Python orchestration
**Status:** Complete (91% test coverage)

### 9. OpenAI Client
**Purpose:** LLM integration for semantic extraction
**Input:** Prompts for value/definition extraction
**Output:** Structured JSON responses
**Technology:** OpenAI GPT-4o-mini API with retry logic
**Cost:** ~$0.10 per filing average
**Status:** Complete (88% test coverage)

---

## Pipeline Flow

```
UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier
                                        ↓
                              ValueExtractor + DefinitionExtractor
                                        ↓
                                  QualityScorer → Database
```

**Stage 1: Universe Building** (Complete)
- Queries SEC EDGAR for S-1/F-1 filings (2015-2025)
- Classifies: SPACs, first-time issuers, business types
- Result: 7,304 in-scope filings identified

**Stage 2: Extraction** (Complete - Production Ready)
- Downloads filing HTML from SEC
- Segments into paragraphs, tables, sections
- Extracts metric values and definitions using rule-based and LLM approaches
- Scores disclosure quality

**Stage 3: LLM Integration** (Complete)
- OpenAI GPT-4o-mini integration for enhanced extraction
- Hybrid approach: rule-based + LLM fallback
- Cost tracking and token management
- Quote verification for LLM-extracted content
- Automated unit tests with 88-95% coverage

---

## Data Flow: Single Filing Processing

```
Filing Metadata (from Discovery)
    │
    ├─ filing_id: "0001234567-24-000123"
    ├─ company: "Example Corp"
    ├─ cik: "0001234567"
    ├─ filing_date: "2024-03-15"
    ├─ filing_type: "S-1"
    └─ url: "https://sec.gov/..."
    │
    ▼
┌───────────────────────────────────┐
│ 1. Cache Layer                    │
│ Check: data/cache/                │
│   0001234567-24-000123.html       │
│ If missing: Download from SEC     │
└───────────┬───────────────────────┘
            │ HTML (200 pages, 200KB)
            │
    ┌───────┴────────┐
    │                │
    ▼                ▼
┌────────────┐  ┌──────────────┐
│ 2. HTML    │  │ 3. Metric    │
│ Segmenter  │  │ Classifier   │
└─────┬──────┘  └──────┬───────┘
      │                │
      │ Segments       │ Classification flags
      │                │
      └────────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ 4. Extractors│
        │ - Values     │
        │ - Definitions│
        └──────┬───────┘
               │
               │ Extracted data
               │
               ▼
        ┌──────────────┐
        │ 5. QA/Quality│
        │ Scoring      │
        └──────┬───────┘
                │
                │ Quality scores + incidence
                │
                ▼
         ┌──────────────┐
         │ 6. Storage   │
         │ - PostgreSQL │
         │ - All tables │
         └──────────────┘
```

---

## LLM Usage Strategy

### Models and Roles

- **GPT-4o-mini** (primary):
  - Numeric extraction from text segments
  - Definition/methodology summarization
  - Quality scoring (when needed)
  - Cost: $0.15/M input tokens, $0.60/M output tokens

- **Future:** GPT-4o for complex edge cases (currently unused)

### Cost Control Mechanisms

- Filter segments before passing to LLMs (keyword rules first)
- Limit context windows to minimal necessary text
- Cache LLM results by `(filing_id, source_segment_id, task_type)`
- Track token usage and cost per component
- Projected cost: ~$0.10 per filing average

### Reliability and Robustness

- Use structured JSON schemas for all extraction calls
- Implement robust JSON parsing with retries (max 3)
- Quote verification: validate LLM-extracted quotes exist in source text
- If LLM outputs invalid after retries: record `qa_status = 'fail'`, continue pipeline
- Never crash entire pipeline on LLM errors

---

## Scalability and Performance

### Parallelism Model

- **Filing-level parallelism:** Process different filings concurrently in separate workers
- Each worker runs the full pipeline for its assigned filings
- Database writes use short transactions, batched inserts

### Database Considerations

- Use PostgreSQL as primary store
- Key indices on:
  - `filings(is_in_scope_phase1, processing_status, filing_date)`
  - `source_segments(filing_id, segment_type)`
  - `metric_values(filing_id, metric_id)` and `(metric_id, period_end)`
  - `filing_metric_incidence(metric_id, filing_id)`
  - `review_candidates`: partial unique indexes on `(filing_id, source_segment_id, char_position, suggested_metric_id)` for NULL and non-NULL segment cases
  - `suppressed_candidates(winner_candidate_id, suppression_reason)`

### Long-Running Operations

- Runs are **restartable**: Orchestrator resumes from last-known `processing_status` per filing
- Components are idempotent at the filing level
- Processing status tracked: `pending`, `fetched`, `segmented`, `processed`, `failed`

---

## Extensibility to Phase 2 (10-Ks)

The architecture supports Phase 2 (10-K filings) by:

- Reusing the same core schema (all tables support multiple filing types)
- Adding 10-K filings with `form_type = '10-K'` and new scope flag
- Adjusting Universe Builder logic for 10-K selection
- Updating keyword lists and patterns in Metric Classifier for 10-K sections
- Potentially adding metrics (e.g., long-term NRR, GRR, LTV)

The component graph remains the same; only configuration and some extraction rules change.

---

## Technology Stack

### Core Languages & Frameworks
- **Python 3.11+** (primary language)
- **PostgreSQL** (database via psycopg3)
- **OpenAI Python SDK** (LLM integration)

### Key Libraries

| Library | Purpose | Version |
|---------|---------|---------|
| `requests` | HTTP requests to SEC | ≥2.31.0 |
| `beautifulsoup4` | HTML parsing | ≥4.12.0 |
| `lxml` | Fast XML/HTML parsing | ≥5.0.0 |
| `pandas` | Data manipulation | ≥2.0.0 |
| `openai` | GPT API client | ≥1.0.0 |
| `python-dotenv` | Environment config | ≥1.0.0 |
| `psycopg[binary]` | PostgreSQL adapter | ≥3.1.0 |
| `pytest` | Testing framework | ≥7.4.0 |
| `black` | Code formatting | ≥23.0.0 |
| `ruff` | Linting | ≥0.1.0 |

---

## Implementation Status

| Component | Status | Coverage |
|-----------|--------|----------|
| UniverseBuilder | Complete | 93% |
| FilingFetcher | Complete | 94% |
| HTMLSegmenter | Complete | 80% |
| MetricClassifier | Complete | 98% |
| StructureParser | Complete | 97% |
| CandidateDetector | Complete | 97% |
| ContextExtractor | Complete | N/A |
| SegmentEnricher | Complete | 98% |
| ValueExtractor | Complete | 66% |
| DefinitionExtractor | Complete | 89% |
| CohortChartDetector | Complete | 100% (21 tests) |
| QualityScorer | Complete | 100% |
| ExtractionPipeline | Complete | 91% |
| OpenAIClient | Complete | 88% |
| PromptTemplates | Complete | 95% |
| Validation | Complete | 100% |
| **Overall** | **Production Ready** | **87%** |

---

## Key Design Decisions

### 1. Rule-Based First, LLM Second
Keyword matching and pattern detection before expensive LLM calls

### 2. Provenance Tracking
Every extracted value links back to source segment with quote verification

### 3. Idempotent Operations
Re-running any stage is safe (upserts, not inserts)

**Review Candidate Deduplication:**
- Two-phase conflict resolution in `bulk_insert_review_candidates()`
- Phase 1: Within-batch deduplication (highest confidence wins)
- Phase 2: Database conflict resolution via pre-fetch + compare
- Partial unique indexes handle NULL vs non-NULL `source_segment_id` separately
- Suppressed candidates logged to `suppressed_candidates` table with reason codes:
  - `lower_confidence`: Lost confidence comparison at same position+metric
  - `runner_up`: Best alternative metric for position (enables UI quick-select)
- Return contract preserved: `zip(candidates, result_ids, strict=True)` always safe

### 4. Conservative Classification
"Require BOTH" signals for business type exclusions to minimize false positives

### 5. Hybrid Extraction Approach
- Rule-based extraction for structured data (tables) = $0 cost
- LLM only for unstructured text (paragraphs) = minimal cost (~$0.10/filing)
- Quote verification ensures LLM accuracy

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM cost overruns | High | Cost tracking, hybrid approach, GPT-4o-mini preference |
| LLM rate limits | Medium | Retry logic with exponential backoff |
| SEC blocking/throttling | Medium | HTML caching, polite delays, User-Agent |
| Low extraction quality | High | Table-first approach, QA validation, quote verification |
| System crashes | Medium | Checkpointing, transaction safety |
| HTML parsing failures | Low | Try/except, log failures, continue pipeline |
| Metric definition drift | Medium | Versioned extraction configs |

---

## Success Criteria

### Phase 1: Proof of Concept (100 filings)
- ✅ Cost < $10 total
- ✅ >90% success rate
- ✅ Table extraction working
- ✅ LLM extraction working
- ✅ QA validation working

### Phase 2: Pilot (1,000 filings)
- ✅ Cost < $50 total
- ✅ >95% success rate
- ✅ Parallel processing working
- ✅ Progress monitoring working

### Phase 3: Production (7,304+ filings)
- ⏳ Cost < $1,000 total
- ⏳ >95% success rate
- ⏳ <5% manual review needed
- ⏳ Comprehensive QA reports

---

## Related Documentation

- **Data Model:** `docs/architecture/data-model.md` - Database schemas, relationships
- **Extraction Details:** `docs/architecture/extraction-pipeline.md` - Component interfaces, extraction logic
- **LLM Integration:** `docs/architecture/llm-integration.md` - OpenAI integration, prompts, costs
- **Requirements:** `docs/requirements/analytic-requirements.md` - Business requirements
- **Quality Model:** `docs/development/quality-model.md` - QA scoring framework
- **Testing:** `docs/development/testing.md` - Test strategy

---

**Last Updated:** 2026-01-07
**Version:** 2.3
**Status:** Production Ready

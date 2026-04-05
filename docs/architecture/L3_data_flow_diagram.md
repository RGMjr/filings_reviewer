# L3 Data Flow Diagram: Filings Reviewer System

## Overview

The Filings Reviewer is a Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Data flows through discovery, fetching, extraction, review, and validation stages, with two parallel extraction pipelines (V1 production, V2 advanced).

---

## 1. High-Level System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         FILINGS REVIEWER SYSTEM                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  External Sources          Discovery & Fetch        Processing            │
│  ┌────────────────┐       ┌─────────────────┐      ┌────────────────┐   │
│  │ SEC EDGAR API  │       │ UniverseBuilder │      │  V1 Pipeline   │   │
│  │ (S-1, F-1)     │──────>│ Classifiers     │─────>│  (Production)  │   │
│  └────────────────┘       │ FilingFetcher   │      └────────────────┘   │
│                           │ (HTML + Cache)  │              ↓             │
│  ┌────────────────┐       └─────────────────┘      ┌────────────────┐   │
│  │ Transcripts    │            ↓                   │  V2 Pipeline   │   │
│  │ Presentations  │       ┌──────────────┐         │ (Transcripts   │   │
│  │ (Document      │      │ Content      │         │  & Images)     │   │
│  │  Source SPI)   │      │ (HTML/Text)  │         └────────────────┘   │
│  └────────────────┘       └──────────────┘              ↓               │
│                                                   ┌────────────────┐    │
│  ┌────────────────┐       ┌──────────────┐      │ Database       │    │
│  │ Config         │      │ Keyword      │      │ PostgreSQL     │    │
│  │ metric_        │◄─────│ Patterns     │─────>│ + Validation   │    │
│  │ keywords.yaml  │      │ (metric_     │      │ (Gold Std)     │    │
│  └────────────────┘      │ keywords.    │      └────────────────┘    │
│                          │ yaml)        │            ↓                │
│  ┌────────────────┐      └──────────────┘      ┌────────────────┐    │
│  │ LLM Services   │                            │ Flask Web UI   │    │
│  │ (OpenAI        │                            │ Review         │    │
│  │ Vision/Chat)   │                            │ Interface      │    │
│  └────────────────┘                            └────────────────┘    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. V1 Extraction Pipeline (Production)

Processes SEC filings end-to-end using rule-based matching with optional LLM enhancement.

```
┌────────────────────────────────────────────────────────────────────────┐
│                    V1 EXTRACTION PIPELINE                               │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Filing HTML         Segmentation       Classification                │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐           │
│  │ Raw HTML     │──>│ HTMLSegmenter│──>│ MetricClassifier │           │
│  │ from DB      │   │ + XPath      │   │ (keyword match)  │           │
│  └──────────────┘   └──────────────┘   └──────────────────┘           │
│       ↓                   ↓                       ↓                     │
│  ┌─────────────────────────────────┐  ┌──────────────────────┐        │
│  │ SourceSegment                   │  │ Segment metadata:    │        │
│  │ - segment_id                    │  │ - xpath              │        │
│  │ - html_content                  │  │ - document_type      │        │
│  │ - section_type (MD&A, Risk...)  │  │ - is_metric_content  │        │
│  │ - xpath                         │  │ - confidence         │        │
│  └─────────────────────────────────┘  └──────────────────────┘        │
│       ↓                                       ↓                        │
│  Enrichment            Value Extraction      Definition Extraction    │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐        │
│  │ Segment      │─────>│ ValueExtractor│     │ Definition   │        │
│  │ Enricher     │      │ (numbers)    │     │ Extractor    │        │
│  │ (context)    │      │ + LLM fallback│    │ (methodolog) │        │
│  └──────────────┘      └──────────────┘     └──────────────┘        │
│       ↓                    ↓                       ↓                   │
│  ┌──────────────────────────────┐  ┌───────────────────────────────┐ │
│  │ MetricValue                  │  │ MetricDefinition              │ │
│  │ - metric_id                  │  │ - definition_id               │ │
│  │ - value (numeric)            │  │ - definition_text             │ │
│  │ - unit                       │  │ - methodology                 │ │
│  │ - confidence                 │  │ - filing_date                 │ │
│  │ - source_segment_id (prov.)  │  │ - confidence                  │ │
│  └──────────────────────────────┘  └───────────────────────────────┘ │
│       ↓                                       ↓                       │
│                    Quality Scoring                                    │
│                    ┌──────────────────┐                              │
│                    │ QualityScorer    │                              │
│                    │ - confidence     │                              │
│                    │ - incidence rate │                              │
│                    │ - richness       │                              │
│                    └──────────────────┘                              │
│                            ↓                                         │
│                    ┌──────────────────┐                              │
│                    │ DATABASE STORAGE │                              │
│                    │ metric_values    │                              │
│                    │ metric_defs      │                              │
│                    │ source_segments  │                              │
│                    └──────────────────┘                              │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 3. V2 Extraction Pipeline (Advanced)

Modern 13-stage pipeline with table reconstruction, image/OCR support, and structured evidence packing. Used for transcripts and presentations.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        V2 EXTRACTION PIPELINE (13 Stages)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Document Input (HTML/Text)                                                │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │ IngestionStage → Parse HTML/text, extract Segments w/ XPath │           │
│  └──────────────────────────────────────────────────────────────┘           │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ SectionClassificationStage → MD&A, Risk, Legal, Custom...    │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ TableReconstructionStage → header_path, stub_path per cell   │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ ImageTriageStage → chart | table_image | decorative          │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ OCRExtractionStage → Extract labeled values from images      │          │
│  │ (vision_client.py: OpenAI GPT-4o for charts/tables)          │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ CandidateGenerationStage → YAML taxonomy matching            │          │
│  │ Reads: config/metric_keywords.yaml                           │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ ValueBindingStage → Link numbers to metrics structurally     │          │
│  │ (xpath/cell coordinates as proof)                            │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ FalsePositiveFilterStage → V1 FP rules on bound values       │          │
│  │ (13 FP heuristics: 1,538 lines)                              │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ PeriodInferenceStage → Extract fiscal period from headers    │          │
│  │ or context (1,246 lines of date parsing logic)               │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ DefinitionExtractionStage → Methodology + definitions        │          │
│  │ Optional LLM enhancement (openai_client.py)                  │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ FactConstructionStage → Build MetricFact w/ EvidencePack     │          │
│  │ Links: segments, images, binding logic, confidence           │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ DeduplicationStage → By (metric, period, entity, type)       │          │
│  │ Merges duplicates, keeps highest confidence                  │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ ValidationStage → Confidence-based routing & validation       │          │
│  │ High confidence: auto-accept                                 │          │
│  │ Low confidence: flag for human review                        │          │
│  └──────────────────────────────────────────────────────────────┘          │
│         ↓                                                                   │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │ OUTPUT: MetricFact with full provenance                      │          │
│  │ - metric definition                                          │          │
│  │ - value + period + entity                                    │          │
│  │ - evidence_pack (segments, images, binding)                  │          │
│  │ - confidence_score                                           │          │
│  │ - review_status                                              │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Database Schema & Data Flow

PostgreSQL stores all extracted metrics, segments, and review decisions with full provenance tracking.

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          DATABASE (PostgreSQL)                             │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  Core Domain Tables                                                       │
│  ┌─────────────────────┐                                                 │
│  │ companies           │ Filing universe                                 │
│  │ - company_id        │                                                │
│  │ - ticker            │                                                │
│  │ - sec_central_idx   │                                                │
│  └─────────────────────┘                                                │
│         ↓                                                                │
│  ┌──────────────────────┐                                               │
│  │ filings              │ Fetched documents                             │
│  │ - filing_id          │                                               │
│  │ - company_id (FK)    │                                               │
│  │ - form_type (S-1...)  │                                               │
│  │ - filing_date        │                                               │
│  │ - html_content       │ (cached)                                      │
│  └──────────────────────┘                                               │
│         ↓                                                                │
│  ┌──────────────────────┐   ┌───────────────────────┐                   │
│  │ source_segments      │   │ v2_documents (V2)     │                   │
│  │ - segment_id         │   │ - document_id         │                   │
│  │ - filing_id (FK)     │   │ - filing_id (FK)      │                   │
│  │ - html_content       │   │ - document_type       │                   │
│  │ - xpath              │   │ - section_type        │                   │
│  │ - section_type       │   │ - text_content        │                   │
│  │ - is_metric_content  │   └───────────────────────┘                   │
│  └──────────────────────┘           ↓                                   │
│         ↓                    ┌───────────────────────┐                   │
│  ┌──────────────────────┐    │ v2_segments           │                   │
│  │ metric_values (V1)   │    │ - segment_id          │                   │
│  │ - value_id           │    │ - document_id (FK)    │                   │
│  │ - filing_id (FK)     │    │ - segment_type        │                   │
│  │ - metric_id (FK)     │    │ - text_content        │                   │
│  │ - value              │    │ - xpath               │                   │
│  │ - confidence         │    │ - table_cell_path     │                   │
│  │ - source_segment_id  │    │ - image_asset_id (FK) │                   │
│  │   (FK → provenance!) │    └───────────────────────┘                   │
│  └──────────────────────┘                                               │
│         ↓                                                                │
│  ┌──────────────────────┐                                               │
│  │ v2_metric_facts      │ V2 final metrics                              │
│  │ - fact_id            │                                               │
│  │ - doc_id (FK)        │                                               │
│  │ - canonical_metric_id│                                               │
│  │ - value              │                                               │
│  │ - period_start/end   │                                               │
│  │ - confidence         │                                               │
│  │ - evidence_pack      │ (EvidencePack JSON)                           │
│  │ - source_locator     │ (xpath/cell coordinates)                      │
│  └──────────────────────┘                                               │
│         ↓                                                                │
│  ┌──────────────────────┐   ┌───────────────────────┐                   │
│  │ metric_definitions   │   │ v2_definitions (V2)   │                   │
│  │ - metric_id          │   │ - definition_id       │                   │
│  │ - name               │   │ - fact_id (FK)        │                   │
│  │ - category           │   │ - definition_text     │                   │
│  │ - methodology        │   │ - extracted_from      │                   │
│  └──────────────────────┘   └───────────────────────┘                   │
│         ↓                                                                │
│  Review & Validation Tables                                             │
│  ┌──────────────────────┐   ┌───────────────────────┐                   │
│  │ review_candidates    │   │ v2_review_candidates  │                   │
│  │ - candidate_id       │   │ - candidate_id        │                   │
│  │ - filing_id (FK)     │   │ - fact_id (FK)        │                   │
│  │ - metric_id (FK)     │   │ - review_status       │                   │
│  │ - value              │   │ - confidence          │                   │
│  │ - review_status      │   │ - assigned_to         │                   │
│  │ - assigned_to        │   └───────────────────────┘                   │
│  └──────────────────────┘                                               │
│         ↓                                                                │
│  ┌──────────────────────┐   ┌───────────────────────┐                   │
│  │ review_decisions     │   │ v2_review_decisions   │                   │
│  │ - decision_id        │   │ - decision_id         │                   │
│  │ - candidate_id (FK)  │   │ - candidate_id (FK)   │                   │
│  │ - decision_type      │   │ - decision_type       │                   │
│  │ - reviewer_id        │   │ - reviewer_id         │                   │
│  │ - notes              │   │ - notes               │                   │
│  │ - created_at         │   │ - created_at          │                   │
│  └──────────────────────┘   └───────────────────────┘                   │
│         ↓                                                                │
│  Gold Standard / Validation                                             │
│  ┌──────────────────────┐                                               │
│  │ gold_standard/       │ Ground truth (CSV-based)                      │
│  │ golden_set_*.csv     │ - filing_id, metric_id                        │
│  │                      │ - value, period_end                           │
│  │ (data/gold_standard) │ - manually annotated truth set                │
│  │                      │ - loaded by V2Validator                       │
│  └──────────────────────┘                                               │
│         ↓                                                                │
│  ┌──────────────────────┐                                               │
│  │ image_assets (V2)    │ OCR source images                             │
│  │ - asset_id           │                                               │
│  │ - document_id (FK)   │                                               │
│  │ - image_type         │ (chart|table|decorative)                      │
│  │ - file_path          │                                               │
│  │ - ocr_json           │ (OpenAI GPT-4o vision result)                 │
│  │ - extracted_values   │                                               │
│  └──────────────────────┘                                               │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. External Integration Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES & DATA SOURCES                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  SEC EDGAR API (infra/sec_client.py)                                   │
│  ┌─────────────────────────────────────────┐                           │
│  │ • Discover filings (S-1, F-1, 8-K)      │                           │
│  │ • Rate limit: 100ms between requests    │                           │
│  │ • User-Agent: SEC_USER_AGENT env var    │                           │
│  │ • Output: HTML content → FilingFetcher  │                           │
│  └─────────────────────────────────────────┘                           │
│           ↓                                                             │
│  Document Source APIs (infra/document_source.py)                       │
│  ┌──────────────────────────────────────────┐                          │
│  │ • Transcripts (TranscriptSource)         │                          │
│  │ • Presentations (PresentationSource)     │                          │
│  │ • HuggingFace (HuggingFaceSource)        │                          │
│  │ • Financial data (FMPSource)             │                          │
│  └──────────────────────────────────────────┘                          │
│           ↓                                                             │
│  OpenAI API (llm/openai_client.py, llm/vision_client.py)              │
│  ┌──────────────────────────────────────────┐                          │
│  │ • LLM text extraction (GPT-4)            │                          │
│  │ • Vision/OCR (GPT-4o - gpt-4o model)    │                          │
│  │ • Cache layer: PostgreSQL table          │                          │
│  │ • Usage: FallBack to keyword matching    │                          │
│  │         Definition extraction            │                          │
│  │         Chart/table OCR (V2)             │                          │
│  └──────────────────────────────────────────┘                          │
│           ↓                                                             │
│  Metric Keyword Configuration (config/metric_keywords.yaml)            │
│  ┌──────────────────────────────────────────┐                          │
│  │ • YAML taxonomy of customer metrics      │                          │
│  │ • Rule-based patterns (regex + keywords) │                          │
│  │ • READ by: V1 & V2 candidate generation  │                          │
│  │ • Authoritative source (no hardcoding)   │                          │
│  │ • Keys: cm_customers_period_end,         │                          │
│  │         cm_active_customers_total, ...   │                          │
│  └──────────────────────────────────────────┘                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Web Interface & User Interaction Loop

Flask-based review interface with separate APIs for V1/V2 extraction results.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        FLASK WEB APPLICATION                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User Browser                                                            │
│  ┌──────────────────────────────────┐                                   │
│  │ HTML + JavaScript Review UI      │                                   │
│  │ (src/web/templates/base.html)    │                                   │
│  │ (src/web/static/js/review.js)    │                                   │
│  └──────────────────────────────────┘                                   │
│           ↓  ↑                                                           │
│    HTTP  │   │  JSON                                                    │
│           ↓  ↑                                                           │
│  ┌──────────────────────────────────┐                                   │
│  │ Flask App (src/web/app.py)       │                                   │
│  │ - Middleware (security, logging) │                                   │
│  │ - Blueprint registration         │                                   │
│  │ - Database connection pool       │                                   │
│  └──────────────────────────────────┘                                   │
│           ↓                                                              │
│  ┌──────────────────────────────────┐                                   │
│  │ Route Modules:                   │                                   │
│  │                                  │                                   │
│  │ 1) review.py / api.py            │ V1 text metric review             │
│  │    GET /review/filing/{id}       │ candidate listing + decisions     │
│  │    POST /api/review/decision     │                                   │
│  │                                  │                                   │
│  │ 2) review_images.py / api_images │ V1 image review (charts)          │
│  │    GET /review/images/{id}       │ from SEC filings                  │
│  │    POST /api/images/decision     │                                   │
│  │                                  │                                   │
│  │ 3) review_v2.py / api_v2.py      │ V2 fact review (new pipeline)     │
│  │    GET /v2/review/<filing_id>    │ structured facts + evidence       │
│  │    POST /api/v2/decisions        │                                   │
│  │                                  │                                   │
│  │ 4) review_pres_images.py         │ Presentation image review         │
│  │    GET /review/pres-images       │ (file-based decisions.json)       │
│  │    POST /api/pres-images/review  │                                   │
│  └──────────────────────────────────┘                                   │
│           ↓                                                              │
│  ┌──────────────────────────────────┐                                   │
│  │ Database Query Layer             │                                   │
│  │ (infra/db.py DatabaseAdapter)    │                                   │
│  │ - Connection pooling             │                                   │
│  │ - Query results → JSON           │                                   │
│  │ - Upserts for decisions          │                                   │
│  └──────────────────────────────────┘                                   │
│           ↓                                                              │
│  ┌──────────────────────────────────┐                                   │
│  │ PostgreSQL                       │                                   │
│  │ - review_candidates/decisions    │                                   │
│  │ - v2_metric_facts, v2_review_cands │                                   │
│  │ - image decisions                │                                   │
│  └──────────────────────────────────┘                                   │
│           ↓                                                              │
│  ┌──────────────────────────────────┐                                   │
│  │ Human Reviewer Creates           │                                   │
│  │ ✓ Accepts candidate              │ (DECISION_APPROVED)               │
│  │ ✗ Rejects + reason               │ (DECISION_REJECTED)               │
│  │ ⚠ Flags for other reviewer       │ (DECISION_FLAGGED)                │
│  └──────────────────────────────────┘                                   │
│           ↓                                                              │
│  ┌──────────────────────────────────┐                                   │
│  │ Gold Standard Validation         │                                   │
│  │ (gold_standard/v2_validator.py)  │                                   │
│  │ • Compares extraction vs. truth  │                                   │
│  │ • Calculates precision/recall    │                                   │
│  │ • Regression detection           │                                   │
│  └──────────────────────────────────┘                                   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Data Flow Lifecycle: End-to-End Example

**Scenario: Customer metric extraction from an S-1 filing**

```
1. DISCOVERY PHASE
   ┌─────────────────────────────────────────────────┐
   │ SEC EDGAR API (UniverseBuilder)                 │
   │ → Query: "SELECT * FROM company WHERE active"  │
   │ → Returns: (ticker, cik, central_index_key)    │
   └─────────────────────────────────────────────────┘
                    ↓

2. FETCH PHASE
   ┌─────────────────────────────────────────────────┐
   │ FilingFetcher                                   │
   │ → Fetch S-1 HTML from EDGAR                     │
   │ → Cache: database html_content column           │
   │ → Rate limit: 100ms between requests            │
   └─────────────────────────────────────────────────┘
                    ↓

3. SEGMENTATION (V1 & V2 enter here)
   ┌─────────────────────────────────────────────────┐
   │ HTMLSegmenter / IngestionStage                  │
   │ → Parse HTML with lxml                          │
   │ → Extract XPath for each segment                │
   │ → Classify section type (MD&A, Risk...)         │
   │ → Store in source_segments / v2_segments        │
   └─────────────────────────────────────────────────┘
                    ↓

4. PATTERN MATCHING
   ┌─────────────────────────────────────────────────┐
   │ MetricClassifier (V1) / CandidateGeneration (V2)│
   │ → Load metric_keywords.yaml                     │
   │ → Search: "customers", "active users", "paid"  │
   │ → Mark segments containing metric keywords      │
   │ → Confidence score: keyword strength + context  │
   └─────────────────────────────────────────────────┘
                    ↓

5. STRUCTURAL BINDING
   ┌─────────────────────────────────────────────────┐
   │ ValueExtractor (V1) / ValueBindingStage (V2)    │
   │ → Find numbers near keyword                     │
   │ → Verify structure (table cell, next to header) │
   │ → Link with XPath/cell coordinates              │
   │ → Extract period from context (fiscal year)     │
   └─────────────────────────────────────────────────┘
                    ↓

6. VALIDATION & FALSE POSITIVE FILTERING
   ┌─────────────────────────────────────────────────┐
   │ FalsePositiveFilterStage (V2)                   │
   │ → Apply 13 FP heuristics                        │
   │   - Cross-row contamination                     │
   │   - Year-over-year ratio checks                 │
   │   - Metric type incompatibility                 │
   │ → Confidence adjustment: high/low/reject        │
   └─────────────────────────────────────────────────┘
                    ↓

7. OPTIONAL LLM ENHANCEMENT
   ┌─────────────────────────────────────────────────┐
   │ OpenAI Client (fallback for ambiguous cases)    │
   │ → Definition extraction (what does metric mean?)│
   │ → Vision OCR (for charts/images in V2)          │
   │ → Result: cached in llm_cache table             │
   └─────────────────────────────────────────────────┘
                    ↓

8. FINAL METRIC FACT CREATION
   ┌─────────────────────────────────────────────────┐
   │ MetricValue (V1) or MetricFact (V2)             │
   │ metric_id: 'cm_customers_period_end'            │
   │ value: '5,250,000'                              │
   │ period: '2023-12-31'                            │
   │ confidence: 0.95                                │
   │ source_segment_id: 42 ← PROVENANCE!             │
   │ evidence_json: {binding, sections, highlights}  │
   └─────────────────────────────────────────────────┘
                    ↓

9. DATABASE STORAGE
   ┌─────────────────────────────────────────────────┐
   │ INSERT INTO metric_values / v2_metric_facts      │
   │ INSERT INTO review_candidates / v2_review_cands │
   │ → Status: PENDING_REVIEW (confidence < 0.90)    │
   │ → Or: AUTO_ACCEPTED (confidence >= 0.90)        │
   └─────────────────────────────────────────────────┘
                    ↓

10. HUMAN REVIEW LOOP (if needed)
    ┌─────────────────────────────────────────────────┐
    │ Flask UI /review/filing/{filing_id}             │
    │ → Display candidate with evidence               │
    │ → Human decides: APPROVED | REJECTED | FLAGGED  │
    │ → Decision stored: review_decisions table       │
    │ → Status updated in candidates table            │
    └─────────────────────────────────────────────────┘
                    ↓

11. VALIDATION AGAINST GOLD STANDARD
    ┌─────────────────────────────────────────────────┐
    │ V2Validator / UnifiedComparison                 │
    │ → Compare extracted vs. gold standard CSV       │
    │ → Calculate: precision, recall, F1-score        │
    │ → Flag regressions if < 95% match on known set  │
    │ → Report: false positives, false negatives      │
    └─────────────────────────────────────────────────┘
                    ↓

12. OUTPUT
    ┌─────────────────────────────────────────────────┐
    │ Extraction Report:                              │
    │ "Extracted 3 metrics from S-1"                  │
    │ - Total Customers (period-end): APPROVED       │
    │ - Active Customers: PENDING_REVIEW              │
    │ - Paid Customers: AUTO_ACCEPTED                 │
    │ Validation: 2/3 match gold standard            │
    └─────────────────────────────────────────────────┘
```

---

## 8. Key Configuration & Control Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                  CONFIGURATION & RUNTIME CONTROLS                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Environment Variables (src/infra/logging_config.py, web/app.py)       │
│  ┌──────────────────────────────────────────┐                           │
│  │ DATABASE_URL                  PostgreSQL   │                           │
│  │ SEC_USER_AGENT               EDGAR access  │                           │
│  │ OPENAI_API_KEY               LLM services  │                           │
│  │ FILINGS_API_KEY              Web auth      │                           │
│  │ DB_POOL_MIN_SIZE=2           Connection    │                           │
│  │ DB_POOL_MAX_SIZE=10          pooling       │                           │
│  │ LOG_LEVEL=INFO               Logging       │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  Metric Keyword Configuration (config/metric_keywords.yaml)            │
│  ┌──────────────────────────────────────────┐                           │
│  │ cm_customers_period_end:                 │                           │
│  │   keywords:                              │                           │
│  │     - "total customers"                  │                           │
│  │     - "paid customers"                   │                           │
│  │   category: "customer_count"              │                           │
│  │   unit: "count"                          │                           │
│  │   confidence_base: 0.85                  │                           │
│  │                                          │                           │
│  │ cm_active_customers_total:               │                           │
│  │   keywords:                              │                           │
│  │     - "active (customers|users)"         │                           │
│  │     - "monthly active"                   │                           │
│  │   category: "engagement"                 │                           │
│  │   unit: "count"                          │                           │
│  │   confidence_base: 0.80                  │                           │
│  │   [etc. ~50+ metrics]                    │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  Pipeline Configuration (extraction_v2/pipeline.py)                     │
│  ┌──────────────────────────────────────────┐                           │
│  │ PipelineConfig:                          │                           │
│  │   enable_section_classification = True   │                           │
│  │   enable_image_extraction = True         │                           │
│  │   enable_chart_extraction = True         │                           │
│  │   min_confidence_auto_accept = 0.90      │                           │
│  │   min_confidence_no_review = 0.85        │                           │
│  │                                          │                           │
│  │ Config.for_transcript():                 │                           │
│  │   - Wider proximity windows              │                           │
│  │   - Relaxed FP filter                    │                           │
│  │                                          │                           │
│  │ Config.for_presentation():               │                           │
│  │   - Images enabled by default            │                           │
│  │   - min_paragraph_chars = 20             │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  SQL Schema (sql/ directory)                                            │
│  ┌──────────────────────────────────────────┐                           │
│  │ 00 init               Create databases     │                           │
│  │ 01 create_schema      Core tables          │                           │
│  │ 02 add_filing_storage HTML storage        │                           │
│  │ 03 create_analysis    Metric analysis     │                           │
│  │ 07 create_review      Review schema       │                           │
│  │ 09 v2_schema          V2 extraction       │                           │
│  │ 12 v2_documents       Transcripts         │                           │
│  │ ... (17 total)                           │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Data Quality & Validation Layers

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      VALIDATION & QUALITY ASSURANCE                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Rule-Based Extraction Validation                                       │
│  ┌──────────────────────────────────────────┐                           │
│  │ extraction/extraction_validation.py       │                           │
│  │ • Numeric format checks                  │                           │
│  │ • Unit compatibility (millions vs. units) │                           │
│  │ • Period format validation                │                           │
│  │ • Metric type matching                    │                           │
│  │ → Fails unrealistic values (negative $)   │                           │
│  │ → Validates period progression            │                           │
│  └──────────────────────────────────────────┘                           │
│           ↓                                                              │
│  LLM Vision-Based Chart OCR                                             │
│  ┌──────────────────────────────────────────┐                           │
│  │ llm/vision_client.py (OpenAI GPT-4o)     │                           │
│  │ • Extract labeled values from charts      │                           │
│  │ • Parse table cells with visual context   │                           │
│  │ • Cached results in llm_cache table       │                           │
│  │ • Never interpolates (only labeled)       │                           │
│  └──────────────────────────────────────────┘                           │
│           ↓                                                              │
│  False Positive Filtering (13 heuristics)                               │
│  ┌──────────────────────────────────────────┐                           │
│  │ false_positive_filter.py (V2)             │                           │
│  │ 1. Cross-row contamination check          │                           │
│  │ 2. Year-over-year ratio validation        │                           │
│  │ 3. Metric type incompatibility            │                           │
│  │ 4. Confidence penalty for low match       │                           │
│  │ 5-13. [8 more semantic filters]           │                           │
│  │ → Output: confidence multiplier (0-1)     │                           │
│  │ → Rejects: confidence → 0 (auto-reject)   │                           │
│  └──────────────────────────────────────────┘                           │
│           ↓                                                              │
│  Confidence Scoring (QualityScorer)                                     │
│  ┌──────────────────────────────────────────┐                           │
│  │ quality_scorer.py                         │                           │
│  │ • Keyword match strength                  │                           │
│  │ • Contextual signals (section type)       │                           │
│  │ • Numeric proximity score                 │                           │
│  │ • Period inference confidence             │                           │
│  │ • Table structure coherence               │                           │
│  │ → Final score: 0.0 - 1.0                  │                           │
│  │ → Thresholds:                             │                           │
│  │    >= 0.90: AUTO_ACCEPTED                 │                           │
│  │    0.85-0.89: PENDING_REVIEW              │                           │
│  │    < 0.85: REJECTED                       │                           │
│  └──────────────────────────────────────────┘                           │
│           ↓                                                              │
│  Gold Standard Validation (pytest -m gold_standard)                    │
│  ┌──────────────────────────────────────────┐                           │
│  │ gold_standard/v2_validator.py             │                           │
│  │ • Load CSV golden standard (ground truth) │                           │
│  │ • Extract metrics using current pipeline  │                           │
│  │ • Compare: extracted vs. truth            │                           │
│  │ • Metrics:                                │                           │
│  │   - Precision (TP / (TP + FP))            │                           │
│  │   - Recall    (TP / (TP + FN))            │                           │
│  │   - F1-score                              │                           │
│  │ • Regression check: F1 < 0.95 → FAIL      │                           │
│  │ • Report: per-filing, per-metric details  │                           │
│  └──────────────────────────────────────────┘                           │
│           ↓                                                              │
│  Human Review (Manual Override)                                         │
│  ┌──────────────────────────────────────────┐                           │
│  │ review_candidates → review_decisions      │                           │
│  │ • Decision types:                         │                           │
│  │   APPROVED (accept extraction)             │                           │
│  │   REJECTED (mark as FP, log reason)       │                           │
│  │   FLAGGED (escalate to other reviewer)    │                           │
│  │ • Reviewer notes for learning             │                           │
│  │ • Feeds back into FP filter tuning        │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Execution Paths for Different Document Types

```
┌─────────────────────────────────────────────────────────────────────────┐
│             EXECUTION PATHS BY DOCUMENT TYPE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  SEC FILINGS (S-1, F-1)                                                │
│  ┌──────────────────────────────────────────┐                           │
│  │ Source: SEC EDGAR API                    │                           │
│  │ Format: HTML with embedded tables/images │                           │
│  │ Extraction: V1 (production) OR V2 (new)  │                           │
│  │ Tables: Reconstructed (V2 only)          │                           │
│  │ Images: OCR via Vision API (V2 optional) │                           │
│  │ Storage: source_segments / v2_documents  │                           │
│  │ Review: Web UI (/review/filing/{id})     │                           │
│  │ Config: PipelineConfig() [default]       │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  EARNINGS CALL TRANSCRIPTS                                             │
│  ┌──────────────────────────────────────────┐                           │
│  │ Source: Transcript APIs (SPI, Seeking…)  │                           │
│  │ Format: Plain text                       │                           │
│  │ Extraction: V2 only                      │                           │
│  │ Tables: No reconstruction needed         │                           │
│  │ Images: None                             │                           │
│  │ Storage: v2_documents (doc_type=trans)   │                           │
│  │ Review: Web UI (/v2/review/<filing_id>)  │                           │
│  │ Config: PipelineConfig.for_transcript()  │                           │
│  │         - Wider proximity windows        │                           │
│  │         - Relaxed FP filtering           │                           │
│  │         - No image extraction            │                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
│  INVESTOR PRESENTATIONS (PDF→images)                                    │
│  ┌──────────────────────────────────────────┐                           │
│  │ Source: SEC EDGAR or company websites    │                           │
│  │ Format: PDF (slides) → extracted images  │                           │
│  │ Extraction: V2 only (image-heavy)        │                           │
│  │ Tables: Extracted from slide images      │                           │
│  │ Images: Primary data source (OCR heavy)  │                           │
│  │ Storage: v2_documents (doc_type=pres)    │                           │
│  │ Review: File-based UI (/review/pres-img) │                           │
│  │ Config: PipelineConfig.for_presentation()│                           │
│  │         - Images enabled by default      │                           │
│  │         - min_paragraph_chars=20         │                           │
│  │ State: _image_decisions.json (file-based)│                           │
│  └──────────────────────────────────────────┘                           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Summary: Key Principles

1. **Rule-based first, LLM second**: All extraction starts with keyword matching; LLM only for ambiguity
2. **Provenance tracking**: Every metric links back to `source_segment_id` (the evidence)
3. **Idempotent pipelines**: Re-running any stage upserts, never duplicates
4. **Conservative classification**: "Require BOTH" signals minimize false positives
5. **Two-pipeline architecture**: V1 (stable, production) + V2 (advanced, transcripts/images)
6. **Gold standard validation**: Before committing, compare against ground truth with F1 ≥ 0.95
7. **Configuration-driven**: All metric patterns in `metric_keywords.yaml`, no hardcoding

---

## Related Documentation

- **Architecture decisions**: `docs/architecture/extraction-decisions.md`
- **Testing & validation**: `docs/development/testing.md`
- **Metric taxonomy**: `config/metric_keywords.yaml`
- **Database schema**: `sql/*.sql`
- **V2 pipeline details**: `.claude/rules/v2-pipeline.md`

# SEC Filings Analysis System - Architecture Overview

**Version:** 2.0
**Last Updated:** 2025-11-14
**Status:** Design Specification

---

## Executive Summary

This system extracts structured customer metrics from SEC filings (S-1, 10-K) at scale. It processes ~17,000-21,000 filings using a hybrid approach combining rule-based table extraction with selective LLM processing to achieve 95% cost reduction while maintaining high quality.

### Key Metrics
- **Target Volume:** 17,000-21,000 filings (10 years S-1, 3 years 10-K)
- **Target Cost:** $500-$1,000 (vs $8,500-$21,000 naive approach)
- **Target Quality:** ≥95% metric extraction accuracy
- **Target Time:** 2-5 days wall-clock time
- **Architecture:** Stateless agent with parallel processing

---

## Design Principles

### 1. Cost Optimization First
- Rule-based extraction for structured data (tables) = $0
- LLM only for unstructured text (paragraphs) = minimal cost
- Use GPT-4o-mini (94% cheaper) with GPT-4o validation fallback
- Keyword filtering reduces LLM input by 90%

### 2. Stateless Agent Architecture
- Each filing processed independently (pure function)
- No hidden state or dependencies between filings
- Reproducible results (same input → same output)
- Crash-resistant with incremental storage

### 3. Separation of Concerns
```
Discovery → Caching → Processing → QA → Storage
    ↓          ↓          ↓        ↓       ↓
  Clean    Clean      Clean    Clean   Clean
Interface Interface Interface Interface Interface
```

### 4. Resilience at Scale
- HTML caching (avoid re-downloads)
- Retry logic with exponential backoff
- Error classification (transient vs permanent)
- Checkpointing every N filings
- Progress tracking and cost monitoring

### 5. Filing-Type Agnostic
- Configurable extraction rules per filing type
- S-1 config (IPO focus: growth metrics)
- 10-K config (Annual focus: financial metrics)
- Easy to extend to 10-Q, 8-K, etc.

---

## System Architecture

### High-Level Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                     USER INTERACTION                             │
└───────────────────────────────┬──────────────────────────────────┘
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
                       │   │ 2. Table Extractor (rules)   │  │
                       │   │                              │  │
                       │   │ 3. Keyword Filter (regex)    │  │
                       │   │                              │  │
                       │   │ 4. LLM Extractor (4o-mini)   │  │
                       │   │                              │  │
                       │   │ 5. QA Agent (validation)     │  │
                       │   │                              │  │
                       │   │ 6. Selective Re-extraction   │  │
                       │   │    (GPT-4o if needed)        │  │
                       │   └──────────────────────────────┘  │
                       └───────────┬──────────────────────────┘
                                   │
                       ┌───────────▼────────────┐
                       │   Storage Layer        │
                       │   ┌─────────────────┐  │
                       │   │ SQLite Database │  │
                       │   │  - metrics      │  │
                       │   │  - keywords     │  │
                       │   │  - qa_warnings  │  │
                       │   │  - exec_log     │  │
                       │   │  - failures     │  │
                       │   │  - costs        │  │
                       │   └─────────────────┘  │
                       │   ┌─────────────────┐  │
                       │   │ CSV Exports     │  │
                       │   └─────────────────┘  │
                       └────────────────────────┘
```

---

## Core Components

### 1. Discovery Service
**Purpose:** Find and catalog SEC filings by date range and type
**Input:** Date range, filing type (S-1, 10-K)
**Output:** List of filing metadata (CIK, accession number, URL, company)
**Technology:** SEC EDGAR API, BeautifulSoup
**Cost:** $0

### 2. Cache Layer
**Purpose:** Store downloaded HTML to avoid re-fetching from SEC
**Input:** Filing ID (CIK-AccessionNumber)
**Output:** HTML content (from cache or fresh download)
**Technology:** Filesystem storage
**Cost:** ~500MB-1GB disk per 1,000 filings

### 3. Table Extractor (Rule-Based)
**Purpose:** Extract metrics from HTML tables (50-70% of all metrics)
**Input:** HTML content
**Output:** Structured metrics with high confidence
**Technology:** BeautifulSoup + regex patterns
**Cost:** $0
**Quality:** High (tables are inherently structured)

### 4. Keyword Filter
**Purpose:** Reduce document size by 90% before LLM processing
**Input:** HTML content
**Output:** Relevant paragraphs only
**Technology:** Regex, ftfy for text normalization
**Cost:** $0

### 5. LLM Extractor (GPT-4o-mini)
**Purpose:** Extract metrics from unstructured text (30-50% of metrics)
**Input:** Filtered paragraphs
**Output:** Structured metrics with medium confidence
**Technology:** OpenAI GPT-4o-mini API
**Cost:** $0.15 per M input tokens, $0.60 per M output tokens

### 6. QA Agent
**Purpose:** Validate extraction quality, flag issues
**Input:** Extracted metrics
**Output:** Confidence scores, warnings, validation flags
**Technology:** Python rule-based validation
**Cost:** $0

### 7. Selective Re-extraction (GPT-4o)
**Purpose:** Re-process low-confidence extractions with better model
**Input:** Flagged filings (~5-10% of total)
**Output:** High-quality metrics
**Technology:** OpenAI GPT-4o API
**Cost:** $2.50 per M input tokens (but only 5-10% of filings)

### 8. Parallel Orchestrator
**Purpose:** Coordinate processing of thousands of filings
**Input:** Batch configuration
**Output:** Completed batch with metrics
**Technology:** ThreadPoolExecutor, rate limiting, progress tracking
**Cost:** $0

### 9. Storage Layer
**Purpose:** Persist results incrementally, enable queries
**Input:** Metrics, warnings, execution logs
**Output:** SQLite database + CSV exports
**Technology:** SQLite3, pandas
**Cost:** $0

### 10. Monitoring Dashboard
**Purpose:** Real-time progress, cost tracking, error monitoring
**Input:** Processing events
**Output:** Console dashboard with stats
**Technology:** tqdm, rich (Python libraries)
**Cost:** $0

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
│ 2. Table   │  │ 3. Keyword   │
│ Extractor  │  │ Filter       │
└─────┬──────┘  └──────┬───────┘
      │                │
      │ 15 metrics     │ 50 paragraphs (5KB)
      │ from tables    │ with customer keywords
      │                │
      │                ▼
      │         ┌──────────────┐
      │         │ 4. LLM       │
      │         │ Extractor    │
      │         │ (4o-mini)    │
      │         └──────┬───────┘
      │                │
      │ 15 metrics     │ 8 metrics from text
      │                │
      └────────┬───────┘
               │
               │ 23 total metrics
               │
               ▼
        ┌──────────────┐
        │ 5. QA Agent  │
        │ Validation   │
        └──────┬───────┘
               │
        ┌──────┴────────┐
        │               │
        ▼               ▼
  Confidence ≥ 0.7   Confidence < 0.7
        │               │
        │               ▼
        │        ┌──────────────┐
        │        │ 6. Re-extract│
        │        │ (GPT-4o)     │
        │        └──────┬───────┘
        │               │
        └───────┬───────┘
                │
                │ Final metrics with confidence scores
                │
                ▼
         ┌──────────────┐
         │ 7. Storage   │
         │ - SQLite DB  │
         │ - QA warnings│
         │ - Keywords   │
         │ - Cost log   │
         └──────────────┘
```

---

## Cost Model

### Per-Filing Cost Breakdown

| Component | Avg Tokens | Model | Cost/Filing |
|-----------|-----------|-------|-------------|
| Table extraction | 0 | Rules | $0.00 |
| Keyword filtering | 0 | Regex | $0.00 |
| LLM extraction (90% of filings) | 5,000 input<br>1,000 output | GPT-4o-mini | $0.0013 |
| Re-extraction (10% of filings) | 10,000 input<br>2,000 output | GPT-4o | $0.045 |
| **Average per filing** | | | **$0.03-$0.06** |

### Total Cost Projection

| Scenario | Filings | Cost |
|----------|---------|------|
| S-1 (10 years) | ~2,500 | $75-$150 |
| 10-K (3 years) | ~18,000 | $540-$1,080 |
| **Total** | **~20,500** | **$615-$1,230** |

**Safety margin:** $500-$1,000 (allowing for re-runs, testing)

---

## Performance Model

### Processing Time

| Factor | Value |
|--------|-------|
| Table extraction | ~1 sec/filing |
| LLM extraction (4o-mini) | ~3-5 sec/filing |
| Re-extraction (4o) | ~5-8 sec/filing |
| Network I/O | ~2-3 sec/filing |
| **Average per filing** | **~6-8 seconds** |

### Parallelization

| Workers | Filings/hour | Total time (20,500 filings) |
|---------|--------------|----------------------------|
| 1 | 450 | 45 hours |
| 5 | 2,000 | 10 hours |
| 10 | 3,500 | 6 hours |
| 20 | 5,000 | 4 hours |

**Recommendation:** 10 workers (balances speed vs rate limits)

**Expected total time:** 6-10 hours of processing + setup/monitoring = **2-3 days**

---

## Technology Stack

### Core Languages & Frameworks
- **Python 3.11+** (primary language)
- **SQLite 3** (database)
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
| `ftfy` | Text normalization | ≥6.1.0 |
| `tqdm` | Progress bars | ≥4.65.0 |
| `rich` | Dashboard UI | ≥13.0.0 |
| `pyyaml` | Config file parsing | ≥6.0.0 |
| `tenacity` | Retry logic | ≥8.2.0 |

### Development Tools
- **pytest** (testing)
- **black** (code formatting)
- **mypy** (type checking)
- **ruff** (linting)

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
- ✅ Rate limiting working
- ✅ Progress monitoring working

### Phase 3: Production (20,500 filings)
- ✅ Cost < $1,500 total
- ✅ >95% success rate
- ✅ <5 days total runtime
- ✅ <5% manual review needed
- ✅ Comprehensive QA reports

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenAI cost overruns | High | Cost tracking, auto-stop at limit |
| OpenAI rate limits | Medium | Rate limiter with backoff |
| SEC blocking/throttling | Medium | HTML caching, polite delays |
| Low extraction quality | High | Table-first approach, QA validation |
| System crashes | Medium | Checkpointing, SQLite transactions |
| HTML parsing failures | Low | Try/except, log failures |
| Metric definition drift | Medium | Versioned extraction configs |

---

## Next Steps

1. **Review this architecture** with stakeholders
2. **Read detailed component specs** (documents 02-07)
3. **Set up development environment** (document 08)
4. **Implement Phase 1** (proof of concept)
5. **Validate approach** on 100 filings
6. **Iterate and scale** to production

---

## Document Index

- **01_ARCHITECTURE_OVERVIEW.md** ← You are here
- **02_SYSTEM_COMPONENTS.md** - Detailed component specifications
- **03_DATA_MODELS.md** - Database schemas, CSV formats, API contracts
- **04_TABLE_EXTRACTION.md** - Rule-based extraction logic
- **05_LLM_EXTRACTION.md** - Prompt engineering, model selection
- **06_IMPLEMENTATION_GUIDE.md** - Step-by-step build instructions
- **07_TESTING_STRATEGY.md** - Quality validation approach
- **08_DEPLOYMENT_GUIDE.md** - Running at scale

---

**Questions or feedback?** Contact: Rob Markey

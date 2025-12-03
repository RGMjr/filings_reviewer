# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based system for analyzing SEC S-1/F-1 filings to assess how companies disclose customer-related metrics. The project supports the Customer Metrics Accounting Standards Board (CMASB) initiative by:

- Discovering and classifying IPO filings from SEC EDGAR
- Extracting customer metrics, definitions, and methodologies
- Assessing disclosure quality and comparability
- Demonstrating the need for standardized customer metrics disclosure

## Architecture Overview

The system uses a modular pipeline architecture with components in `src/`:

```
src/
├── infra/                    # Infrastructure layer
│   ├── db.py                 # PostgreSQL adapter (psycopg3)
│   └── sec_client.py         # SEC EDGAR API client
│
├── universe/                 # Phase 1: Filing Discovery
│   ├── classifiers.py        # SPAC, first-time issuer, business type detection
│   └── universe_builder.py   # Discovers and classifies S-1/F-1 filings
│
├── filing_fetcher/           # Phase 2a: Document Retrieval
│   └── filing_fetcher.py     # Downloads and caches filing HTML
│
└── extraction/               # Phase 2b: Metric Extraction
    ├── models.py             # Data classes (SourceSegment, MetricValue, etc.)
    ├── html_segmenter.py     # Splits HTML into sections/paragraphs/tables
    ├── metric_classifier.py  # Identifies segments containing metrics
    ├── value_extractor.py    # Extracts numeric values from segments
    ├── definition_extractor.py # Extracts metric definitions
    ├── quality_scorer.py     # Scores disclosure quality (0-3 scale)
    └── extraction_pipeline.py # Orchestrates full extraction flow
```

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

**Stage 2: Extraction** (40% implemented)
- Downloads filing HTML from SEC
- Segments into paragraphs, tables, sections
- Extracts metric values and definitions
- Scores disclosure quality

## Database Schema

PostgreSQL with key tables:
- `companies` - Issuer metadata (CIK, name, ticker, SIC code)
- `filings` - Filing documents with classification flags
- `source_segments` - Parsed sections from filings
- `metric_values` - Extracted numeric values
- `metric_definitions` - Extracted definitions/methodologies
- `filing_metric_incidence` - Quality scores per filing/metric

Schema files in `sql/`:
- `01_create_schema.sql` - Core tables
- `03_create_analysis_schema.sql` - Extraction tables
- `04_seed_metrics_taxonomy.sql` - Metric definitions

## Key Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test module
pytest tests/unit/extraction/test_value_extractor.py -v

# Format code
black src/ tests/

# Lint code
ruff check src/ tests/

# Build universe (requires database)
python scripts/build_universe_real.py --start-date 2015-01-01 --end-date 2025-12-31

# Fetch sample filings
python scripts/fetch_curated_sample.py
```

## Environment Setup

Create a `.env` file (see `.env.template`):
```bash
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
SEC_USER_AGENT="YourName contact@example.com"
```

## SEC EDGAR Integration

**Rate Limiting**: The `SECClient` class enforces 100ms minimum between requests per SEC guidelines.

**User-Agent**: All SEC requests require a User-Agent header with contact info. Set via `SEC_USER_AGENT` env var.

**Data Sources**:
- Submissions API: `https://data.sec.gov/submissions/CIK{cik}.json`
- Filing documents: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/`

## Testing Standards

- **Minimum coverage**: 75% (enforced in pytest.ini)
- **Current coverage**: 76%
- **Test structure**: `tests/unit/` for fast isolated tests, `tests/integration/` for database tests

Integration tests require PostgreSQL. Set `TEST_DATABASE_URL` environment variable.

## Key Design Decisions

1. **Rule-based first, LLM second**: Keyword matching and pattern detection before expensive LLM calls
2. **Provenance tracking**: Every extracted value links back to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts, not inserts)
4. **Conservative classification**: "Require BOTH" signals for business type exclusions to minimize false positives

## Current Implementation Status

| Component | Status | Coverage |
|-----------|--------|----------|
| UniverseBuilder | Complete | 98% |
| FilingFetcher | Complete | 99% |
| HTMLSegmenter | Complete | 92% |
| MetricClassifier | Complete | 95% |
| ValueExtractor | Complete | 97% |
| DefinitionExtractor | Complete | 90% |
| QualityScorer | Complete | 100% |
| ExtractionPipeline | Complete | 85% |
| LLM Integration | Not started | - |

## Documentation

- `docs/01_ANALYTIC_REQUIREMENTS.md` - Business requirements
- `docs/02_METRIC_TAXONOMY_AND_DEFINITIONS.md` - Metric definitions
- `docs/03_DATA_MODEL_SPEC.md` - Database schema details
- `docs/04_SYSTEM_ARCHITECTURE.md` - Component design
- `docs/05_COMPONENT_INTERFACE_SPECS.md` - Python interfaces
- `docs/06_QA_AND_QUALITY_MODEL.md` - Quality scoring framework
- `DEVELOPMENT_PLAN.md` - Sprint tracking and roadmap

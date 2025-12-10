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
│   ├── sec_client.py         # SEC EDGAR API client
│   ├── validation.py         # Input validation utilities (CIK, dates, SIC codes)
│   └── logging_config.py     # Centralized logging configuration
│
├── universe/                 # Phase 1: Filing Discovery
│   ├── classifiers.py        # SPAC, first-time issuer, business type detection
│   └── universe_builder.py   # Discovers and classifies S-1/F-1 filings
│
├── filing_fetcher/           # Phase 2a: Document Retrieval
│   └── filing_fetcher.py     # Downloads and caches filing HTML
│
├── extraction/               # Phase 2b: Metric Extraction
│   ├── models.py             # Data classes (SourceSegment, MetricValue, etc.)
│   ├── html_segmenter.py     # Splits HTML into sections/paragraphs/tables
│   ├── metric_classifier.py  # Identifies segments containing metrics
│   ├── value_extractor.py    # Extracts numeric values from segments
│   ├── definition_extractor.py # Extracts metric definitions
│   ├── quality_scorer.py     # Scores disclosure quality (0-3 scale)
│   └── extraction_pipeline.py # Orchestrates full extraction flow
│
├── review/                   # Human-in-the-Loop Review System
│   ├── models.py             # Data classes (ReviewCandidate, ReviewDecision, etc.)
│   ├── candidate_generator.py # Generate review candidates from filing segments
│   ├── number_parsing.py     # Extract and parse numbers from text (P1.3)
│   ├── keyword_matching.py   # Find metric keywords near numbers (P1.3)
│   ├── false_positive_filter.py # Filter false positive numbers (P1.3)
│   ├── context_extraction.py # Extract context around positions (P1.3)
│   └── feature_extractor.py  # Extract ML features from candidates
│
├── web/                      # Flask Web Application (In Progress)
│   ├── app.py                # Flask application factory
│   ├── routes/               # Route handlers (review, api)
│   ├── templates/            # Jinja2 HTML templates
│   └── static/               # CSS, JavaScript assets
│
└── llm/                      # LLM Integration
    ├── openai_client.py      # OpenAI API client with retry logic and cost tracking
    └── prompts.py            # Prompt templates for metric extraction
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

**Stage 2: Extraction** (Complete - Production Ready)
- Downloads filing HTML from SEC
- Segments into paragraphs, tables, sections
- Extracts metric values and definitions using rule-based and LLM approaches
- Scores disclosure quality

**Stage 3: LLM Integration** (Complete)
- OpenAI GPT-4o-mini integration for enhanced extraction
- Hybrid approach: rule-based + LLM fallback
- Cost tracking and token management
- Automated unit tests with 88-95% coverage

**Stage 4: Human Review System** (In Progress)
- Flask-based web interface for human review of extraction candidates
- Candidate generation with ML features for pattern analysis
- Pattern learning from review decisions to improve extraction rules
- See `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` for implementation roadmap

## Review Module Architecture (P1.3 Module Splitting)

The review system uses a modular architecture where `candidate_generator.py` orchestrates several specialized modules:

```
candidate_generator.py (orchestrator - 243 statements, 98% coverage)
├── number_parsing.py        # Extract numbers: $1.2M, 45%, 50,000
│                            # (55 statements, 95% coverage)
├── keyword_matching.py      # Find metric keywords near numbers
│                            # Pre-compiled patterns, distance calculation
│                            # (49 statements, 100% coverage)
├── false_positive_filter.py # Filter dates, years, page refs, small values
│                            # Configurable thresholds, returns (bool, reason)
│                            # (45 statements, 100% coverage)
└── context_extraction.py    # Extract N words around position
                             # Supports word-position caching (P1.2 optimization)
                             # (34 statements, 100% coverage)
```

**Benefits of Module Splitting:**
- Each module has single responsibility (SOLID principles)
- 100% test coverage on extracted modules vs. 23% before splitting
- Easier to test, modify, and reuse components independently
- candidate_generator.py reduced by 43% (428 → 243 statements)
- Total: 426 statements with 98% average coverage across 5 modules

**Feature Extractor (B2):**

In addition to the candidate generation pipeline, the review system includes a feature extraction module (`src/review/feature_extractor.py`) that computes ML features for pattern analysis:
- **71 statements, 100% coverage, 90 tests**
- Keyword proximity features (distance, position)
- Context features (definition language, period mentions, risk factors)
- Number format features (integer, decimal, percentage, currency)
- Section features (table vs paragraph, section name)
- Magnitude features (log10 of value)
- Unit normalization for consistency
- Performance tested with 1,000-10,000 candidate volumes

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
- `07_create_review_schema.sql` - Human review tables (in progress)

### Security
- **API Key Management**: All API keys are managed through environment variables in `.env` file (which is gitignored). Never commit API keys to the repository.
- The `.env.template` file provides a template with placeholders for all required API keys.

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

## Docker Setup

The project includes `docker-compose.yml` for running PostgreSQL locally:

```bash
# Start PostgreSQL container (port 5433)
docker compose up -d

# Connection details:
# - Host: localhost
# - Port: 5433
# - User: dev
# - Password: dev
# - Database: filings_analysis

# For Docker-based development:
DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis

# For integration tests:
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test

# Stop the container
docker compose down

# Stop and remove data volume
docker compose down -v
```

The SQL files in `sql/` are automatically applied when the container first starts.

## SEC EDGAR Integration

**Rate Limiting**: The `SECClient` class enforces 100ms minimum between requests per SEC guidelines.

**User-Agent**: All SEC requests require a User-Agent header with contact info. Set via `SEC_USER_AGENT` env var.

**Data Sources**:
- Submissions API: `https://data.sec.gov/submissions/CIK{cik}.json`
- Filing documents: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/`

## Testing Standards

- **Minimum coverage**: 75% (enforced in pyproject.toml)
- **Current coverage**: 77% overall (467 tests passing)
  - Core extraction modules: 80-100% coverage
  - LLM modules: 88-95% coverage
  - Validation module: 100% coverage
- **Test structure**: `tests/unit/` for fast isolated tests, `tests/integration/` for database tests
- **Configuration**: All pytest, coverage, black, and ruff settings in `pyproject.toml`

**Error Handling:**
- Specific exception types used throughout (ValueError, IOError, requests.HTTPError)
- Database operations return success indicators
- File system and network errors distinguished from validation errors

Integration tests require PostgreSQL. Set `TEST_DATABASE_URL` environment variable.

## Key Design Decisions

1. **Rule-based first, LLM second**: Keyword matching and pattern detection before expensive LLM calls
2. **Provenance tracking**: Every extracted value links back to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts, not inserts)
4. **Conservative classification**: "Require BOTH" signals for business type exclusions to minimize false positives

## Current Implementation Status

| Component | Status | Coverage |
|-----------|--------|----------|
| UniverseBuilder | Complete | 93% |
| FilingFetcher | Complete | 94% |
| HTMLSegmenter | Complete | 80% |
| MetricClassifier | Complete | 98% |
| ValueExtractor | Complete | 66% |
| DefinitionExtractor | Complete | 89% |
| QualityScorer | Complete | 100% |
| ExtractionPipeline | Complete | 91% |
| OpenAIClient | Complete | 88% |
| PromptTemplates | Complete | 95% |
| Validation | Complete | 100% |
| ReviewModels | In Progress | - |
| FlaskApp | In Progress | - |

**Input Validation:** Centralized validation module (`src/infra/validation.py`) provides:
- CIK validation and normalization
- Accession number format validation
- SIC code validation (range 0100-9999)
- Date and date range validation
- Form type validation

**Logging:** Centralized logging configuration (`src/infra/logging_config.py`) provides:
- Consistent format across all scripts: `timestamp - module - level - message`
- Optional file logging for long-running scripts (logs written to `logs/` directory)
- All scripts use `configure_logging()` for setup

```python
from src.infra.logging_config import configure_logging, get_timestamped_log_path

# Console only
configure_logging(level="INFO")

# Console + file logging
configure_logging(level="INFO", log_file=get_timestamped_log_path("extraction"))

# With line numbers for debugging
configure_logging(level="DEBUG", include_debug_context=True)
```

## Documentation

The documentation has been reorganized for clarity and ease of navigation. Start with `docs/README.md` for the complete index.

### Quick Reference

**Architecture (System Design):**
- `docs/architecture/system-overview.md` - Complete system architecture (START HERE)
- `docs/architecture/data-model.md` - Database schema and table specifications
- `docs/architecture/extraction-pipeline.md` - Extraction pipeline components and flow
- `docs/architecture/llm-integration.md` - OpenAI GPT-4o-mini integration details

**Requirements (Business Needs):**
- `docs/requirements/analytic-requirements.md` - Business requirements and research questions
- `docs/requirements/CMASB_PRIORITY_METRICS_PHASE1.md` - Priority metrics

**Development (Implementation):**
- `docs/development/metrics-taxonomy.md` - Canonical metric definitions
- `docs/development/quality-model.md` - Quality scoring framework (0-3 scale)
- `docs/development/testing.md` - Test strategy and coverage requirements

**Operations (Running the System):**
- `docs/operations/setup-guide.md` - Environment setup and configuration
- `docs/operations/08_DEPLOYMENT_GUIDE.md` - Deployment procedures

**Other:**
- `DEVELOPMENT_PLAN.md` - Sprint tracking and roadmap
- `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` - Human review system implementation plan
- `docs/archive/` - Historical phase summaries and fix documentation

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

**Stage 4: Human Review System** (In Progress - D1/D2 Complete)
- Flask-based web interface for human review of extraction candidates (COMPLETE)
- Candidate generation with ML features for pattern analysis (COMPLETE)
- Review routes with 7 production-ready improvements (D1 - COMPLETE)
- REST API endpoints for review decisions (D2 - COMPLETE)
- Pattern learning from review decisions to improve extraction rules (In Progress - E1)
- See `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` for full implementation roadmap
- See `docs/D1_IMPROVEMENTS_FINAL.md` for D1 completion details

## Review Module Architecture

The review system uses a modular architecture with specialized, focused modules:

```
candidate_generator.py (orchestrator - ~370 lines, 98% coverage)
├── exceptions.py            # Custom exception hierarchy
│                            # CandidateGenerationError, SegmentProcessingError, NumberProcessingError
│                            # (50 lines, 100% coverage)
├── confidence_scoring.py    # Multi-signal confidence computation
│                            # ConfidenceScorer class + METRIC_EXPECTED_FORMATS config
│                            # (220 lines, 100% coverage)
├── helpers.py               # DB orchestration helpers
│                            # generate_candidates_for_filing() convenience function
│                            # (90 lines, 100% coverage)
├── number_parsing.py        # Extract numbers: $1.2M, 45%, 50,000
│                            # (55 statements, 95% coverage)
├── keyword_matching.py      # Find metric keywords near numbers
│                            # Pre-compiled patterns, distance calculation
│                            # (49 statements, 100% coverage)
├── false_positive_filter.py # Filter dates, years, page refs, small values
│                            # Configurable thresholds, returns (bool, reason)
│                            # (45 statements, 100% coverage)
├── context_extraction.py    # Extract N words around position
│                            # Supports word-position caching (P1.2 optimization)
│                            # (34 statements, 100% coverage)
└── feature_extractor.py     # Compute ML features for pattern analysis
                             # (630 statements, 100% coverage)
```

**Benefits of Modular Architecture:**
- Each module has single clear responsibility (SOLID principles)
- 98%+ test coverage across all modules
- Exception hierarchy reusable across review module
- ConfidenceScorer independently testable
- DB helpers separated from algorithm
- Easier to test, modify, and reuse components independently
- candidate_generator.py reduced by 53% (970 → ~450 lines)

**Feature Extractor (B2):**

In addition to the candidate generation pipeline, the review system includes a feature extraction module (`src/review/feature_extractor.py`) that computes ML features for pattern analysis:
- **~630 statements total, 100% coverage, 115 tests** (including P2.4 enhancements)

**Base Features**:
- Keyword proximity features (distance, position)
- Context features (definition language, period mentions, risk factors)
- Number format features (integer, decimal, percentage, currency)
- Section features (table vs paragraph, section name)
- Magnitude features (log10 of value)
- Unit normalization for consistency
- Performance tested with 1,000-10,000 candidate volumes

**Derived Features (P2.4)**:
- Binning functions (2): `bin_keyword_distance()`, `bin_value_magnitude()` for interpretability
- Interaction features (1): `compute_distance_magnitude_interaction()` for non-linear relationships
- Composite signals (3): `compute_strong_signal()`, `compute_weak_signal()`, `compute_very_weak_signal()`
- Convenience function: `compute_all_derived_features()` for batch computation
- All features computed on-demand from base features (no database schema changes)

**Pattern Analyzer (E1):**

The pattern analyzer discovers high-precision patterns from human review decisions to improve extraction rules:
- **~2,200 statements total, 97% average coverage, 85 unit tests + 8 integration tests**
- **Production-ready** with P1 (high-impact) and P2 (medium-impact) improvements complete

**Core Features**:
- Pure Python statistical functions (no scipy/numpy dependencies):
  - `statistical_tests.py` (95 statements, 99% coverage) - chi-squared test, t-test, performance metrics
  - P1.1: P-value calculations (Wilson-Hilferty χ² approximation, normal t-test approximation)
- Feature importance analysis:
  - Categorical features: chi-squared test for association with decisions
  - Numeric features: t-test for group differences (accept vs reject)
  - Significance filtering (α = 0.05, 0.01, 0.001)
- Pattern discovery:
  - Single-feature patterns (categorical values, numeric quartile thresholds)
  - P2.1: Multi-feature conjunctive patterns (top N features combined with AND logic)
  - Precision/recall/F1 evaluation using `LearnedPattern.matches()`
  - Configurable minimum precision (default: 0.75) and support (default: 5)
- Database integration:
  - Method: `get_all_reviewed_candidates_with_decisions()` for cross-filing analysis
  - P2.2: Database-side pattern evaluation using PostgreSQL JSONB operators (10-100x speedup)
  - Pattern persistence with optional auto-approval threshold

**Advanced Capabilities (P1 & P2)**:
- P1.2: Cross-validation with stratified k-fold for pattern stability detection
- P1.3: Pattern conflict detection (contradictory and redundant patterns)
- P2.3: Natural language pattern explanations with examples and metrics interpretation
- P2.4: Feature engineering helpers (7 functions: binning, interaction, composite signals)

**Usage Example**:
```python
# Initialize analyzer
analyzer = PatternAnalyzer(db, min_pattern_precision=0.80)

# Analyze with cross-validation and multi-feature patterns
patterns = analyzer.discover_patterns_with_cross_validation(
    pattern_type='reject_rule',
    include_two_feature_patterns=True,
    use_db_evaluation=True  # Fast evaluation for large datasets
)

# Check for conflicts before saving
conflicts = analyzer.detect_pattern_conflicts(patterns)
if not conflicts['contradictory'] and not conflicts['redundant']:
    analyzer.save_patterns(patterns, auto_approve_threshold=0.90)

# Generate explanations for review
for pattern in patterns[:5]:
    explanation = analyzer.generate_pattern_explanation(pattern)
    print(explanation)
```

**Documentation**: See `docs/E1_IMPROVEMENTS_TRACKING.md` for complete P1/P2 implementation details

## Review Module Configuration

The review system uses centralized configuration via `src/review/config.py`:

### Basic Usage

```python
from src.review import CandidateGenerator
from src.infra.db import DatabaseAdapter

# Use default configuration
db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
generator = CandidateGenerator()

# Generate candidates for a filing
segments = db.get_source_segments_for_filing(filing_id=123)
candidates = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    db=db,
)

# Save to database
db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
print(f"Generated {len(candidates)} candidates")
```

### Configuration Presets

The system provides three presets for common scenarios:

**High Precision** (minimize false positives):
```python
from src.review.config import get_high_precision_config

# Stricter proximity, higher thresholds
config = get_high_precision_config()
generator = CandidateGenerator(config=config)

# Results: Fewer candidates, higher quality, less review burden
```

**High Recall** (catch all potential metrics):
```python
from src.review.config import get_high_recall_config

# Looser proximity, lower thresholds, disabled filtering
config = get_high_recall_config()
generator = CandidateGenerator(config=config)

# Results: More candidates, may include false positives, comprehensive coverage
```

**Fast** (optimize for speed):
```python
from src.review.config import get_fast_config

# Disable expensive computations (confidence scoring, pattern matching)
config = get_fast_config()
generator = CandidateGenerator(config=config)

# Results: Faster processing, suitable for prototyping or large-scale batch processing
```

### Custom Configuration

For fine-tuned control, create a custom configuration:

```python
from src.review.config import CandidateGenerationConfig

# Adjust parameters for your use case
custom_config = CandidateGenerationConfig(
    max_keyword_distance=75,       # Moderate proximity (default: 100)
    min_metric_value=50,           # Filter small numbers (default: 10)
    apply_learned_rules=True,      # Use learned patterns from E1 (default: True)
    min_pattern_precision=0.80,    # High-confidence patterns only (default: 0.75)
    compute_confidence=True,       # Enable confidence scoring (default: True)
    filter_false_positives=True,   # Enable FP filtering (default: True)
    context_words=40,              # Context extraction window (default: 40)
)
generator = CandidateGenerator(config=custom_config)
```

### Convenience Wrapper

For simple use cases, use the convenience wrapper:

```python
from src.review.helpers import generate_candidates_for_filing

# One-liner for basic workflows
candidates = generate_candidates_for_filing(
    db=db,
    filing_id=123,
    company_id=456,
)
```

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_keyword_distance` | 100 | Maximum characters between number and metric keyword |
| `context_words` | 40 | Words to extract in each direction for context |
| `min_metric_value` | 10 | Minimum numeric value to consider (filters single digits) |
| `filter_false_positives` | True | Apply false positive filtering (dates, years, page refs) |
| `filter_years` | True | Filter year-like numbers (1990-2100) |
| `compute_confidence` | True | Compute confidence scores for candidates |
| `apply_learned_rules` | True | Apply learned patterns from E1 filtering |
| `min_pattern_precision` | 0.75 | Minimum precision for learned patterns to be applied |
| `cache_word_positions` | True | Cache word positions for context extraction (P1.2 optimization) |

### Backward Compatibility

The generator maintains backward compatibility with individual parameters:

```python
# Old style (still works, but deprecated)
generator = CandidateGenerator(
    max_keyword_distance=50,
    filter_false_positives=True,
    min_value=100,
)

# New style (recommended)
from src.review.config import CandidateGenerationConfig
config = CandidateGenerationConfig(
    max_keyword_distance=50,
    filter_false_positives=True,
    min_metric_value=100,
)
generator = CandidateGenerator(config=config)
```

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

## Claude Skills (AI Development Tools)

**Purpose:** Reduce context window usage and ensure consistency when working with Claude Code.

### Available Skills

| Skill | File | Version | Use Case |
|-------|------|---------|----------|
| **Implementation Planner** | `.claude/skills/implementation-planner.md` | v1.1 ✅ | Generate structured plans with A/B/C streams, dependencies, time estimates + **actual time tracking** |
| **Flask API Builder** | `.claude/skills/flask-api-builder.md` | v1.0 ✅ | Generate Flask routes, API endpoints, validation, tests (D1/D2 patterns) |
| **Code Module Grader** | `.claude/skills/code-module-grader.md` | v1.1 ✅ | Evaluate modules A+ to F, generate P1/P2/P3 improvements + **completion tracking** |
| **Test Coverage Analyzer** | `.claude/skills/test-coverage-analyzer.md` | v1.1 ✅ | Find coverage gaps, generate test files + **before→after improvement tracking** |
| **Database Migration Helper** | `.claude/skills/database-migration-helper.md` | v1.0 ✅ | Generate SQL migrations + db.py methods + tests |
| **Completion Report Generator** | `.claude/skills/completion-report-generator.md` | v1.0 ✅ | Generate comprehensive completion reports when phases finish |
| **Refactor Evaluator** | `.claude/skills/refactor-evaluator.md` | v1.0 ✅ | Evaluate refactoring opportunities, compare approaches, recommend best path |
| **Documentation Sync Validator** | `.claude/skills/documentation-sync-validator.md` | v1.0 ✅ | Detect stale documentation, outdated metrics, missing references |

### How to Use Skills

**Direct invocation (recommended):**
```
"Use implementation-planner skill to create a plan for [feature description]"
```

**Examples:**

*Planning a new feature:*
```
"Use implementation-planner skill to plan:
- Export review decisions to CSV/JSON
- Include filtering by date range and status
- Add progress indicator for large exports"
```

*Building a new Flask route:*
```
"Use flask-api-builder skill to create:
- POST /api/filings/<filing_id>/export endpoint
- Accepts format parameter (csv, json, xlsx)
- Returns export_id and status_url
- Include validation and integration tests"
```

*Evaluating code quality:*
```
"Use code-module-grader skill to grade src/extraction/metric_classifier.py"
```

*Improving test coverage:*
```
"Use test-coverage-analyzer skill to:
- Analyze src/review/pattern_analyzer.py
- Find files below 75% coverage
- Generate tests for quick wins (files with <10 missing statements)"
```

*Creating database migrations:*
```
"Use database-migration-helper skill to create:

Table: user_preferences
Columns:
- preference_id (PK)
- user_id (FK to users, CASCADE delete)
- preferences (JSONB)
- created_at, updated_at (TIMESTAMPTZ)

Include db.py methods and integration tests."
```

*Generating completion reports:*
```
"Use completion-report-generator skill to create report for:

Phase: E1 P1 Improvements
Original plan: docs/E1_IMPROVEMENTS_TRACKING.md
Completed: 2025-12-10

Results:
- 3 P1 improvements complete
- Time: 7 hours (estimate: 7-9 hours)
- 26 new tests added
- 99% coverage achieved

Generate full completion report with lessons learned."
```

*Evaluating refactoring opportunities:*
```
"Use refactor-evaluator skill to analyze:

Module: src/extraction/metric_classifier.py
Concerns: 850 lines, high complexity, multiple responsibilities
Consider: Extract helper modules vs split into classes vs keep as-is
Show: Approach comparison with risk assessment"
```

*Validating documentation:*
```
"Use documentation-sync-validator skill to:
- Check CLAUDE.md and DEVELOPMENT_PLAN.md
- After refactoring candidate_generator.py
- Focus on: file_references, coverage_metrics, module_structure
- Show quick wins (< 5 min fixes)"
```

**Claude will:**
1. Load the skill (encodes project patterns)
2. Generate code following established patterns (TypedDict, validation, error handling)
3. Include comprehensive tests (unit + integration)
4. Apply D1/D2 production-readiness improvements
5. Match existing code style (review.py, api.py conventions)

**Result:** 70%+ reduction in context needed, perfect consistency with project patterns.

### Documentation

- **Quick-Start Guide:** `docs/CLAUDE_SKILLS_QUICKSTART.md` - How to use and create skills
- **Development Plan:** `docs/CLAUDE_SKILLS_DEVELOPMENT_PLAN.md` - Roadmap for remaining skills
- **Skills Directory:** `.claude/skills/` - All skill files

### Why Skills Matter

**Without skills:**
- 5,000+ tokens explaining project patterns
- 10-15 minutes explaining format requirements
- Risk of inconsistency across planning sessions

**With skills:**
- 500 tokens to invoke
- 30 seconds to request
- Guaranteed consistency with project conventions

### Skills-On-Demand Approach

**All core skills complete** (8/8):
- **Planning & Implementation:** Implementation Planner, Flask API Builder
- **Quality & Testing:** Code Module Grader, Test Coverage Analyzer
- **Database:** Database Migration Helper
- **Process & Maintenance:** Completion Report Generator, Refactor Evaluator, Documentation Sync Validator

**Result:** Comprehensive skill coverage for the full development lifecycle - from planning to implementation to completion to maintenance.

### Skill Enhancements (v1.1 Updates)

**December 2025 enhancements:**
- **Implementation Planner v1.1:** Added actual time tracking, completion date tracking, enhanced "Notes & Decisions" section
- **Code Module Grader v1.1:** Added status field, actual time field, assigned field, completion date tracking
- **Test Coverage Analyzer v1.1:** Added before→after coverage visualization, test count growth tracking, "Expected Result" celebration format

These enhancements match actual usage patterns from E1/D1 improvement tracking and enable better estimation accuracy over time.

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
- **Current coverage**: 83% overall (475+ tests passing)
  - Core extraction modules: 80-100% coverage
  - Infrastructure modules: 87-100% coverage (SECClient, Pool, Validation, HTTPClient)
  - LLM modules: 88-95% coverage
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
| SECClient | Complete | 87% |
| ConnectionPool | Complete | 90% |
| HTTPClient | Complete | 97% |
| ReviewModels | Complete | 56% |
| CandidateGenerator | Complete | 98% (modular) |
| FeatureExtractor | Complete | 100% |
| ReviewRoutes (D1) | Complete | 94% |
| APIRoutes (D2) | Complete | 97% |
| ReviewTemplate (D4) | Complete | 94% |
| ReviewJavaScript (D5) | Complete | Manual |
| ProductionServer (D6) | Complete | Manual |
| PatternAnalyzer (E1) | Complete | 95% |
| StatisticalTests (E1) | Complete | 99% |

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

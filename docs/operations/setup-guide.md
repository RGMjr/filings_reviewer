# Setup Guide

**Version:** 3.0
**Last Updated:** 2026-02-05

---

## Overview

This guide walks you through setting up the SEC Filings Reviewer development environment from scratch. The system requires Python 3.11+, PostgreSQL (via Docker or local installation), and several API keys for full functionality.

---

## Prerequisites

- **Python 3.11 or higher** (check with `python --version`)
- **Git** for cloning the repository
- **Docker Desktop** (recommended) or PostgreSQL 15+ installed locally
- **OpenAI API key** for LLM-based metric extraction
- **SEC EDGAR User-Agent** (your name and email) for compliant API access

---

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/RGMjr/filings_reviewer_v2.git
cd filings_reviewer_v2
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# OR
venv\Scripts\activate     # On Windows
```

### 3. Install Dependencies

Install from the curated `requirements.txt` (DO NOT use `pip freeze`):

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- **Core runtime**: psycopg3, requests, beautifulsoup4, lxml, PyYAML
- **LLM integration**: openai, tiktoken
- **Web framework**: flask, waitress
- **Testing**: pytest, pytest-cov, pytest-benchmark
- **Development tools**: black, ruff, mypy

### 4. Configure Environment Variables

Copy the environment template and configure your settings:

```bash
cp .env.template .env
```

Edit `.env` with your configuration:

```bash
# OpenAI API Configuration
# Get your API key from: https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-your-actual-key-here

# SEC EDGAR User-Agent (REQUIRED by SEC.gov)
# Format: "YourName your.email@example.com"
SEC_USER_AGENT="John Doe john.doe@example.com"

# Database Configuration
# If using Docker Compose (recommended):
DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis
TEST_DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis_test

# LLM Response Cache (reduces API costs)
LLM_CACHE_ENABLED=true
LLM_CACHE_PATH=data/llm_cache.db
LLM_CACHE_VERSION=v1

# Flask Configuration (optional in development)
SECRET_KEY=
APP_ENV=development

# API Authentication (optional in development)
FILINGS_API_KEY=
API_KEY_REQUIRED=false
```

**Important environment variables**:
- `OPENAI_API_KEY`: **Required** for LLM extraction (get from [OpenAI Platform](https://platform.openai.com/api-keys))
- `SEC_USER_AGENT`: **Required** by SEC EDGAR (format: "Name email@example.com")
- `DATABASE_URL`: PostgreSQL connection string
- `TEST_DATABASE_URL`: Separate test database (recommended)

### 5. Start PostgreSQL Database

#### Option A: Docker Compose (Recommended)

Start PostgreSQL container on port 5433:

```bash
docker compose up -d
```

Verify it's running:

```bash
docker compose ps
```

You should see `filings-postgres` container running on port 5433.

#### Option B: Local PostgreSQL Installation

If you have PostgreSQL installed locally, create the databases:

```bash
createdb filings_analysis
createdb filings_analysis_test
```

Update your `.env` to use port 5432 instead of 5433:

```bash
DATABASE_URL=postgresql://localhost:5432/filings_analysis
TEST_DATABASE_URL=postgresql://localhost:5432/filings_analysis_test
```

### 6. Run Database Migrations

Apply the SQL schema migrations (00-09 in `sql/` directory):

```bash
python scripts/apply_migrations.py
```

This creates all required tables:
- `companies`, `filings`, `filings_html` (core filing data)
- `source_segments`, `metric_values`, `metric_definitions` (V1 extraction)
- `v2_documents`, `v2_segments`, `v2_metric_facts` (V2 extraction)
- `review_candidates`, `review_decisions`, `review_image_candidates`, `review_image_decisions` (human review)
- `gold_standard_items`, `gold_standard_extractions` (validation)

### 7. Verify Installation

Run the unit test suite to verify everything is working:

```bash
pytest tests/unit/ -v
```

Expected output:
```
============================== test session starts ===============================
...
tests/unit/extraction/test_keyword_filter.py::test_keyword_matching PASSED
tests/unit/extraction/test_metric_classifier.py::test_classification PASSED
tests/unit/universe/test_classifiers.py::test_s1_classifier PASSED
...
========================= XX passed in X.XXs =================================
```

For full test coverage including integration tests:

```bash
pytest -v
```

---

## Running the System

### Build Filing Universe

Discover S-1/F-1 filings from SEC EDGAR and populate the `filings` table:

```bash
python scripts/build_universe_real.py
```

This will:
1. Query SEC EDGAR quarterly index files
2. Filter for S-1 and F-1 filings
3. Insert company and filing records into the database
4. Log progress with filing counts per quarter

### Download Filing HTML

Batch download filing HTML documents:

```bash
python scripts/batch_download_filings.py --limit 10
```

### Run Extraction Pipeline (V1)

Extract customer metrics from filings using the V1 pipeline:

```bash
python scripts/run_extraction_pipeline.py --limit 10
```

Options:
- `--limit N`: Process first N filings
- `--filing-id ID`: Process specific filing
- `--force`: Reprocess already-extracted filings
- `--debug`: Enable debug logging

This executes the full V1 pipeline:
1. `HTMLSegmenter`: Parse HTML into segments
2. `MetricClassifier`: Classify segments by relevance
3. `SegmentEnricher`: Extract tables and context
4. `ValueExtractor`: Extract metric values with LLM
5. `QualityScorer`: Score extraction confidence
6. Store results in `source_segments` and `metric_values` tables

### Run V2 Extraction Pipeline

The V2 pipeline is a ground-up redesign with 10x faster lxml parsing, stable XPath locators, full table reconstruction, and image/OCR integration. Extract metrics from a single filing:

```bash
# By filing ID
python scripts/run_v2_extraction.py --filing-id 1

# By accession number
python scripts/run_v2_extraction.py --accession 0001193125-21-186026
```

Options:
- `--filing-id ID`: Filing ID from database (mutually exclusive with `--accession`)
- `--accession NUM`: SEC accession number (mutually exclusive with `--filing-id`)
- `--dry-run`: Run pipeline without persisting results to database
- `--min-confidence FLOAT`: Minimum confidence for auto-accept (default: 0.90)
- `--no-images`: Disable image extraction
- `--verbose` / `-v`: Enable debug logging

The V2 pipeline executes these stages:
1. **lxml Parse**: Parse filing HTML into a DOM tree
2. **Segment**: Split document into typed content blocks (paragraphs, tables, headings, images)
3. **Table Reconstruct**: Resolve colspan/rowspan and compute header_path/stub_path bindings
4. **Image Extract**: Classify images (chart, table image, decorative) and run OCR where applicable
5. **Keyword Match**: Match metric keywords against segments and table cells
6. **Confidence Score**: Score each extracted fact; auto-accept facts above the confidence threshold
7. **Persist**: Store results in `v2_documents`, `v2_segments`, `v2_metric_facts`, and related tables

The script prints a summary including fact counts, confidence distribution, and metrics breakdown.

For detailed V2 vs V1 comparison and migration guidance, see `docs/V2_MIGRATION_GUIDE.md`.

### Start Web Review Interface

Launch the Flask web application for human review:

```bash
python scripts/run_review_server.py
```

Access at: http://localhost:5000

#### V1 Review Interface

The V1 review interface allows you to:
- Review extracted text segments and metrics
- Approve, reject, or flag uncertain extractions
- Review image-based metrics (charts, graphs)
- Track review progress and decisions

See `docs/HUMAN_REVIEW_SYSTEM.md` for the V1 review workflow.

#### V2 Review Interface

After running V2 extraction, review facts at: http://localhost:5000/v2/review/filings

The V2 review interface provides:
- **Fact-by-fact review** with evidence packs (highlighted HTML, header/stub paths, context)
- **Three decision types**: Accept, Reject (with category), Correct (metric or value override)
- **Keyboard shortcuts**: `A` Accept, `R` Reject, `C` Correct, `N`/Arrow Right Next, `P`/Arrow Left Previous
- **Filtering** by review status, metric type, and sort order (confidence, metric, period)
- **Undo** capability for any decision
- **Auto-advance** to next pending fact after each decision

See `docs/V2_HUMAN_REVIEW_GUIDE.md` for the complete V2 review workflow and API reference.

---

## Development Tools

### Code Formatting

Format code with Black:

```bash
black src/ tests/
```

### Linting

Check code quality with Ruff:

```bash
ruff check src/ tests/
```

Auto-fix issues:

```bash
ruff check src/ tests/ --fix
```

### Type Checking

Run mypy type checker (strict mode on `src/review/`):

```bash
mypy src/review/ --strict
```

### Test Coverage

Generate coverage report:

```bash
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

Current coverage target: 75% minimum (currently at 87%).

### Gold Standard Validation

When modifying extraction code or keyword configuration, run gold standard validation:

```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

See `.claude/rules/gold-standard.md` for the complete validation workflow.

---

## Common Operations

### View Database Tables

Connect to PostgreSQL via psql:

```bash
# Docker Compose setup
docker exec -it filings-postgres psql -U dev -d filings_analysis

# Local PostgreSQL
psql filings_analysis
```

Useful queries:

```sql
-- Count filings by type
SELECT filing_type, COUNT(*) FROM filings GROUP BY filing_type;

-- Recent extractions
SELECT f.company_name, mv.metric_name, mv.value, mv.confidence_score
FROM metric_values mv
JOIN filings f ON mv.filing_id = f.id
ORDER BY mv.created_at DESC
LIMIT 20;

-- Review decisions
SELECT metric_name, decision_type, COUNT(*)
FROM review_decisions
GROUP BY metric_name, decision_type;
```

### Reset Database

To start fresh, drop and recreate:

```bash
# Stop containers
docker compose down -v

# Restart and reapply migrations
docker compose up -d
python scripts/apply_migrations.py
```

### Update Dependencies

The `requirements.txt` is curated with comments. To update packages:

```bash
# Update specific package
pip install --upgrade openai

# Regenerate if needed (manually review changes)
pip freeze > requirements_new.txt
# Merge changes into requirements.txt with comments preserved
```

**Never blindly run `pip freeze > requirements.txt`** as it loses important comments and structure.

---

## Project Structure Reference

```
filings_reviewer_v2/
├── src/
│   ├── infra/               # Database (db.py), SEC client (sec_client.py)
│   ├── universe/            # Filing discovery and classification
│   ├── filing_fetcher/      # Document retrieval and caching
│   ├── extraction/          # V1 extraction pipeline (production)
│   ├── extraction_v2/       # V2 pipeline (production-ready, 10x faster)
│   ├── review/              # Human review workflow
│   ├── web/                 # Flask application (routes/, templates/, static/)
│   ├── llm/                 # OpenAI integration with SQLite caching
│   └── gold_standard/       # Validation framework
├── config/
│   └── metric_keywords.yaml # Metric keyword patterns (authoritative)
├── scripts/                 # Operational scripts (see above)
├── tests/
│   ├── unit/               # Fast unit tests
│   ├── integration/        # Database-dependent tests
│   └── conftest.py         # Pytest fixtures
├── sql/                    # Database schema migrations (00-09)
├── docs/                   # Documentation
├── .env.template           # Environment configuration template
├── requirements.txt        # Curated Python dependencies
└── docker-compose.yml      # PostgreSQL container definition
```

---

## Troubleshooting

### Database Connection Errors

**Error:** `psycopg.OperationalError: connection refused`

**Solutions:**
1. Verify PostgreSQL is running: `docker compose ps`
2. Check port 5433 is available: `lsof -i :5433`
3. Verify `DATABASE_URL` in `.env` matches Docker Compose config
4. Restart container: `docker compose restart`

### SEC EDGAR API Errors

**Error:** `403 Forbidden` or `User-Agent required`

**Solutions:**
1. Set `SEC_USER_AGENT` in `.env` with your name and email
2. Format: `"FirstName LastName your.email@example.com"`
3. SEC requires real contact information (not generic/fake)

### OpenAI API Errors

**Error:** `AuthenticationError: Invalid API key`

**Solutions:**
1. Verify `OPENAI_API_KEY` in `.env` starts with `sk-proj-` or `sk-`
2. Check key at https://platform.openai.com/api-keys
3. Ensure key has sufficient credits/quota

### Missing Test Database

**Error:** `database "filings_analysis_test" does not exist`

**Solutions:**
1. Create test database: `docker exec -it filings-postgres psql -U dev -c "CREATE DATABASE filings_analysis_test;"`
2. Or set `TEST_DATABASE_URL` to use same database (not recommended)

### Import Errors

**Error:** `ModuleNotFoundError: No module named 'src'`

**Solutions:**
1. Activate virtual environment: `source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Verify Python version: `python --version` (should be 3.11+)

---

## Next Steps

After completing setup:

1. **Build universe**: `python scripts/build_universe_real.py`
2. **Download filings**: `python scripts/batch_download_filings.py --limit 10`
3. **Extract metrics (V1)**: `python scripts/run_extraction_pipeline.py --limit 10`
4. **Extract metrics (V2)**: `python scripts/run_v2_extraction.py --filing-id <ID>`
5. **Start review server**: `python scripts/run_review_server.py`
6. **Review V1 results**: http://localhost:5000/filings
7. **Review V2 results**: http://localhost:5000/v2/review/filings
8. **Explore documentation**: See `docs/README.md` for architecture, design decisions, and advanced workflows

For V2 pipeline usage and migration, see `docs/V2_MIGRATION_GUIDE.md`.
For V2 human review workflow and API, see `docs/V2_HUMAN_REVIEW_GUIDE.md`.

For contributing, see `CLAUDE.md` for context-specific rules and available commands.

---

## Support

- **Architecture documentation**: `docs/architecture/system-overview.md`
- **Extraction logic history**: `docs/architecture/extraction-decisions.md`
- **V1 human review system**: `docs/HUMAN_REVIEW_SYSTEM.md`
- **V2 human review guide**: `docs/V2_HUMAN_REVIEW_GUIDE.md`
- **Gold standard validation**: `.claude/rules/gold-standard.md`
- **V2 pipeline migration**: `docs/V2_MIGRATION_GUIDE.md`

For issues or questions, see the project's GitHub issues or contact the maintainers.

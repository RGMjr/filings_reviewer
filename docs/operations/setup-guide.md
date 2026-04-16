# Setup Guide

**Last Updated:** 2026-04-08

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11 or 3.12 | 3.11 is the primary target |
| PostgreSQL | 15+ | Local via Docker or Neon (cloud) |
| uv | latest | Preferred for dependency management |
| git | any | |

Install `uv` if you do not have it:

```bash
pip install uv
```

---

## 1. Clone and Install

```bash
git clone https://github.com/RGMjr/filings_reviewer
cd filings_reviewer
```

Install dependencies:

```bash
uv pip install -r requirements.txt
```

For development tools (pytest, black, ruff, mypy):

```bash
uv pip install -e ".[dev]"
```

---

## 2. Environment Configuration

Copy the template and fill in your values:

```bash
cp .env.template .env
```

The table below documents every variable. Variables marked **Required** must be set before the system will start.

### Core variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string. Local: `postgresql://dev:dev@localhost:5433/filings_analysis`. Neon: `postgresql://user:password@host.neon.tech/dbname?sslmode=require` |
| `TEST_DATABASE_URL` | Tests only | Separate database used by `pytest`. Prevents test runs from touching the main database. |
| `SECRET_KEY` | Production | Flask session secret. Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"`. In development a random key is auto-generated (sessions do not persist across restarts). |
| `OPENAI_API_KEY` | LLM features | OpenAI API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). Required for extraction and quality scoring. |

### Application settings

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Set to `production` to enforce strict validation and require `SECRET_KEY` and `FILINGS_API_KEY`. |
| `FILINGS_API_KEY` | — | API key for web route authentication. Required in production. Generate with `secrets.token_hex(32)`. |
| `API_KEY_REQUIRED` | `false` | Set to `true` to require API key authentication. Always `true` in production. |

### LLM cache

| Variable | Default | Description |
|---|---|---|
| `LLM_CACHE_ENABLED` | `true` | Cache LLM responses in PostgreSQL (via `DATABASE_URL`) to reduce repeat API costs. |
| `LLM_CACHE_VERSION` | `v1` | Increment this string to invalidate all cached responses when prompts change. |

### V2 pipeline settings

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `V2_WORKER_COUNT` | `4` | Default number of parallel workers for batch extraction. |
| `V2_MIN_CONFIDENCE` | `0.5` | Minimum confidence threshold for including extracted facts. |

### Optional integrations

| Variable | Description |
|---|---|
| `FMP_API_KEY` | Financial Modeling Prep API key. Required for transcript ingestion via `scripts/ingest_transcripts.py --source fmp`. Get from [financialmodelingprep.com](https://financialmodelingprep.com/developer/docs/). |
| `SENTRY_DSN` | Sentry error tracking DSN. Uncomment in `.env` to enable. |
| `JSON_LOGS` | Set to `1` to emit structured JSON log output instead of plain text. |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub token for the Claude Code MCP server. Scopes: `repo`, `read:org`. |
| `BRAVE_API_KEY` | Brave Search API key for the Brave Search MCP server. |
| `GEMINI_API_KEY` | Google Gemini API key for the Python Testing MCP server. |

---

## 3. Database Setup

### Option A: Local PostgreSQL via Docker (recommended for development)

The `docker-compose.yml` at the project root starts a PostgreSQL 15 container on port **5433** (to avoid conflicting with any local PostgreSQL instance on 5432).

```bash
docker compose up -d
```

Connection string for `.env`:

```
DATABASE_URL=postgresql://dev:dev@localhost:5433/filings_analysis
```

To stop the container:

```bash
docker compose down
```

Data is persisted in the `pgdata` Docker volume; it survives container restarts.

### Option B: Neon (cloud PostgreSQL)

Neon is used for the production deployment on Render. See `docs/operations/cloud-deployment-runbook.md` for the full provisioning and cutover checklist.

Connection string format:

```
DATABASE_URL=postgresql://user:password@host.neon.tech/dbname?sslmode=require
```

### Running migrations

Once the database is reachable, apply all schema migrations in canonical order:

```bash
python3 scripts/apply_all_migrations.py
```

The script maintains a `schema_migrations` tracking table and skips already-applied files, making re-runs safe. Useful flags:

```bash
# Preview which migrations would be applied without executing
python3 scripts/apply_all_migrations.py --dry-run

# Point at a specific database instead of DATABASE_URL
python3 scripts/apply_all_migrations.py --database-url "postgresql://..."

# For an existing database set up before migration tracking was added:
# record all migrations as applied without re-executing them
python3 scripts/apply_all_migrations.py --mark-all-applied
```

---

## 4. Verify Installation

Run the test suite to confirm everything is wired up correctly:

```bash
pytest -v
```

The default test run excludes slow, gold standard, and integration tests (those requiring a live database). To run integration tests, ensure `TEST_DATABASE_URL` is set and run:

```bash
pytest -v -m integration
```

Minimum coverage is enforced at 75%. To generate a coverage report:

```bash
pytest --cov=src --cov-report=html
```

---

## 5. Running the System

### 5.1 Build the filing universe

Queries SEC EDGAR for S-1/F-1 filings in a date range and populates the `companies` and `filings` tables.

```bash
# Test with a narrow date range first
python3 scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-01-31

# Full Phase 1 range
python3 scripts/build_universe_real.py --start-date 2015-01-01 --end-date 2025-12-31

# Dry run — classifies filings without committing to the database
python3 scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-01-31 --dry-run
```

The `--user-agent` argument defaults to the CMASB contact. SEC policy requires a valid contact email in the User-Agent header; the script will refuse to run without one.

### 5.2 Run extraction on a single filing

```bash
# By filing ID (from the filings table)
python3 scripts/run_v2_extraction.py --filing-id 1

# By SEC accession number
python3 scripts/run_v2_extraction.py --accession 0001193125-21-186026

# Dry run — runs the full pipeline without persisting results
python3 scripts/run_v2_extraction.py --filing-id 1 --dry-run

# Adjust auto-accept confidence threshold (default: 0.90)
python3 scripts/run_v2_extraction.py --filing-id 1 --min-confidence 0.85

# Disable image/chart extraction
python3 scripts/run_v2_extraction.py --filing-id 1 --no-images
```

The script prints a summary table showing facts extracted, confidence distribution, and persistence counts.

### 5.3 Run batch extraction

Processes multiple filings in parallel using `ProcessPoolExecutor`. Supports checkpointing, graceful shutdown (Ctrl+C), and a circuit breaker that aborts on too many consecutive failures.

```bash
# Process all filings (4 workers, default)
python3 scripts/batch_v2_extraction.py

# Process only filings with status 'fetched'
python3 scripts/batch_v2_extraction.py --status fetched

# Limit to first 10 filings
python3 scripts/batch_v2_extraction.py --limit 10

# Resume from a checkpoint (skip filing_ids below this value)
python3 scripts/batch_v2_extraction.py --resume-from 1234

# Custom workers and batch-size (checkpoint interval)
python3 scripts/batch_v2_extraction.py --workers 8 --batch-size 20

# Dry run
python3 scripts/batch_v2_extraction.py --dry-run --limit 5
```

Progress checkpoints are written to `logs/batch_v2_progress.json`. A per-run JSON summary is written to `logs/batch_v2_summary_<timestamp>.json`.

The production cron on Render runs:
```bash
python3 scripts/batch_v2_extraction.py --status fetched --workers 2 --limit 50
```

### 5.4 Run the review web UI

The review interface is a Flask application served by Waitress.

```bash
python3 scripts/run_review_server.py
```

Defaults to `0.0.0.0:8000`. Options:

```bash
python3 scripts/run_review_server.py --host 0.0.0.0 --port 8080 --threads 8
```

The server requires `DATABASE_URL` and `SECRET_KEY` to be set. In production, also set `APP_ENV=production` and `FILINGS_API_KEY`.

Once running:
- Review interface: `http://localhost:8000/filings`
- Health check: `http://localhost:8000/health`

For local development without the Waitress server:

```bash
python3 scripts/run_dev_server.py
```

---

## 6. Project Structure

```
filings_reviewer/
├── src/
│   ├── infra/           # Shared infrastructure: db.py, sec_client.py, http_client.py,
│   │                    #   logging_config.py, pool.py, validation.py, exceptions.py
│   ├── universe/        # Filing discovery: classifiers.py, universe_builder.py
│   ├── filing_fetcher/  # Document retrieval and local caching
│   ├── extraction/      # V1 extraction pipeline (retired — kept for historical reference only)
│   ├── extraction_v2/   # V2 unified extraction pipeline (active production pipeline)
│   │                    #   Handles SEC filings, transcripts, and investor presentations.
│   │                    #   Stages: ingestion, segmentation, keyword filter, LLM extraction,
│   │                    #   false positive filter, persistence, quality scoring.
│   ├── review/          # Human review support: candidate_generator.py, pattern_analyzer.py
│   ├── shared/          # Cross-cutting models and config: models.py, keyword_config.py
│   ├── web/             # Flask application: routes/, templates/, static/
│   ├── llm/             # OpenAI integration with PostgreSQL-backed response cache;
│   │                    #   includes vision_client.py and prompts.py
│   └── gold_standard/   # Validation framework: baseline.py, fresh_extractor.py,
│                        #   v2_validator.py, unified_comparison.py
├── scripts/             # Runnable scripts (see section 5)
├── sql/                 # Schema migration files (00–16)
├── config/
│   └── metric_keywords.yaml   # Authoritative metric keyword patterns
├── data/
│   ├── gold_standard/   # Gold standard filings and annotation files
│   └── llm_cache.db     # LLM response cache (gitignored)
├── tests/               # pytest test suite
├── docs/                # Project documentation
├── docker-compose.yml   # Local PostgreSQL (port 5433)
├── pyproject.toml       # Project metadata, tool config, test config
├── requirements.txt     # Runtime dependencies
└── .env.template        # Environment variable template
```

---

## 7. Development Tools

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type-check the review module (strict mode)
mypy src/review/ --strict
```

Code style targets Python 3.11, line length 100. The V1 `src/extraction/` package has been deleted; V1 modules that are still used moved to `src/shared/`.

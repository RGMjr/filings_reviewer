# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py (PostgreSQL), sec_client.py (SEC EDGAR API)
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction (V1 - production)
├── extraction_v2/  # Image/OCR pipeline (ingestion, image triage, OCR extraction)
├── review/         # Human review: candidate_generator, pattern_analyzer
├── web/            # Flask app: routes/, templates/, static/
├── llm/            # OpenAI integration with SQLite-backed caching
└── gold_standard/  # Validation: baseline.py, fresh_extractor.py
config/
└── metric_keywords.yaml  # Metric keyword patterns (authoritative source)
```

**Pipeline (V1):** UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer → Database

## Key Commands

```bash
pip install -r requirements.txt    # Install dependencies
pytest -v                          # Run all tests
pytest --cov=src --cov-report=html # Run with coverage
black src/ tests/                  # Format code
ruff check src/ tests/             # Lint
mypy src/review/ --strict          # Type checking
```

## Environment Setup

```bash
# .env file (see .env.template)
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
SEC_USER_AGENT="YourName contact@example.com"
```

## Docker

```bash
docker compose up -d   # Start PostgreSQL (port 5433)
docker compose down    # Stop
# Connection: postgresql://dev:dev@localhost:5433/filings_analysis
```

## Database

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `review_candidates`, `review_decisions`. Schema files in `sql/` (00-08).

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` passes `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)

## Core Design Principles

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives

## Web Routes

- `src/web/routes/review.py` / `api.py`: Text/metric review interface
- `src/web/routes/review_images.py` / `api_images.py`: Image review interface
- API auth: `@require_api_key` decorator, configure via `FILINGS_API_KEY` env var

## SEC EDGAR Integration

- **Rate Limiting**: 100ms minimum between requests
- **User-Agent**: Required via `SEC_USER_AGENT` env var

## Documentation

See `docs/README.md` for complete index. Key docs:
- `docs/architecture/system-overview.md` - System architecture
- `docs/architecture/extraction-decisions.md` - Extraction logic history
- `docs/HUMAN_REVIEW_SYSTEM.md` - Review workflow

## Context-Specific Rules

Claude Code loads path-specific rules automatically from `.claude/rules/`:
- `extraction.md` - Loaded when editing `src/extraction/**` or `config/metric_keywords.yaml`
- `gold-standard.md` - Loaded when working with gold standard validation

## Available Commands

Use these slash commands for workflows:
- `/task-create [ID]` - Create a worker prompt for a task
- `/task-run [ID]` - Execute an existing worker prompt
- `/ralph [mode]` - Start Ralph Loop for autonomous execution
- `/metric-lifecycle` - Guide for adding/removing metrics

## Gold Standard Validation

**Required** when modifying extraction code or keyword config:
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```
See `.claude/rules/gold-standard.md` for full workflow (auto-loaded when relevant).

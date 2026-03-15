# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py, sec_client.py, http_client.py, logging_config.py, pool.py, validation.py, exceptions.py
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction (V1 - production)
├── extraction_v2/  # Image/OCR pipeline (NOT in production — V2 was reverted; code present but inactive)
├── review/         # Human review: candidate_generator, pattern_analyzer
├── web/            # Flask app: routes/, templates/, static/
├── llm/            # OpenAI integration with SQLite-backed caching; includes vision_client.py and prompts.py
└── gold_standard/  # Validation: baseline.py, fresh_extractor.py
config/
└── metric_keywords.yaml  # Metric keyword patterns (authoritative source)
```

**Pipeline (V1):** UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer → Database

## Key Commands

```bash
uv pip install -r requirements.txt # Install dependencies
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

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `review_candidates`, `review_decisions`. Schema files in `sql/` (00-09).

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` passes `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)
- **Before committing**: Run the full test suite (`pytest -x -q`). If fixing one failure breaks others, continue iterating until all pass in a single run before committing.

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
- `testing.md` - Loaded when editing `tests/**`

## Available Commands

Use these slash commands for workflows:
- `/task-create [ID]` - Create a worker prompt for a task
- `/task-run [ID]` - Execute an existing worker prompt
- `/ralph [mode]` - Start Ralph Loop for autonomous execution
- `/metric-lifecycle` - Guide for adding/removing metrics
- `/commit` - Safe commit: runs ruff + pytest before committing
- `/merge-check` - Thorough merge readiness assessment (CI, migrations, imports, tests)
- `/ci-fix` - Autonomous CI fix loop: iterates ruff → mypy → pytest until all pass
- `/plan-execute` - Execute a multi-phase plan with parallel sub-agents per independent wave

## Implementation Rules

- Execute ONLY the steps specified. Do not expand scope, fix adjacent issues, or refactor beyond what was asked.
- When given a numbered plan, implement exactly those items. Do not add extra steps or address anything not listed.
- If you notice a related issue while working, call it out to the user rather than silently fixing it.

## Git Operations

- Before any force-push, force-merge, rebase, or reset --hard: show the exact command, show current branch/HEAD state, and wait for explicit user confirmation ("yes" — not a number, not ambiguous input).
- Never interpret ambiguous input as approval for destructive git operations.
- Never use `git add -A` or `git add .` without explicit user instruction. Stage specific files by name.

## Code Review / Audits

- When performing merge readiness assessments or code audits, do a thorough deep pass the first time. Do not produce superficial reports.
- Always check: CI status on the branch, migration file registration and ordering, import statements in changed files.
- Dropped imports and empty regex patterns from config moves are common failure modes — check for these explicitly.

## Shell Commands

- For multi-line shell commands, use heredocs or chain with `&&` / `;` on a single line.
- Do not use bare newlines between commands — they break in zsh.

## Gold Standard Validation

**Required** when modifying extraction code or keyword config:
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```
See `.claude/rules/gold-standard.md` for full workflow (auto-loaded when relevant).

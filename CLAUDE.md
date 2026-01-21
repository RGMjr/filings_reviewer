# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py (PostgreSQL), sec_client.py (SEC EDGAR API), validation.py
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction: html_segmenter, metric_classifier, keyword_config, value_extractor, segment_enricher, cohort_chart_detector, context_extractor, structure_parser, candidate_detector
├── review/         # Human review: candidate_generator, pattern_analyzer, rule_applicator, table_structure
├── web/            # Flask app: routes/, templates/, static/
├── llm/            # OpenAI integration: openai_client.py, prompts.py
└── gold_standard/  # Validation: baseline.py, fresh_extractor.py
config/
└── metric_keywords.yaml  # Externalized metric keyword patterns (editable without code changes)
```

**Pipeline:** UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer → Database

**Review system config:** See `src/review/config.py` for `CandidateGenerationConfig` and presets (`get_high_precision_config()`, etc.)

## Database Schema

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `filing_metric_incidence`, `review_candidates`, `review_decisions`, `learned_patterns`. Schema files in `sql/` (00-08).

API keys go in `.env` (gitignored). See `.env.template`.

## Key Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html

# Format and lint
black src/ tests/
ruff check src/ tests/

# Type checking (review module)
mypy src/review/ --strict

# Structural code search (ast-grep)
ast-grep scan .                                    # Run all rules
ast-grep run --pattern 'PATTERN' --lang python .  # Pattern search
```

## Code Search with ast-grep

Use ast-grep for structural code searches (function definitions, decorators, patterns). Config in `sgconfig.yml`, rules in `ast-grep-rules/`.

```bash
ast-grep run --pattern 'def $FUNC($$$ARGS):' --lang python src/
```

## Environment Setup

```bash
# Create .env file (see .env.template)
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
SEC_USER_AGENT="YourName contact@example.com"
```

## Docker Setup

```bash
# Start PostgreSQL (port 5433)
docker compose up -d

# Connection: postgresql://dev:dev@localhost:5433/filings_analysis
# Test DB: postgresql://dev:dev@localhost:5433/filings_analysis_test

# Stop
docker compose down
```

## Flask Review Server

**Port requirement**: Always use port **5002** or **5003** (never 5000).

```bash
python scripts/run_review_server.py  # Runs on port 5002
# Visit http://localhost:5002/review/images
```

## Claude Code MCP Servers (Optional)

```bash
claude mcp add --transport stdio playwright -- npx -y @playwright/mcp@latest  # Browser automation
claude mcp add github -- npx -y @anthropic-ai/mcp-github                       # GitHub operations
```

## SEC EDGAR Integration

- **Rate Limiting**: 100ms minimum between requests per SEC guidelines
- **User-Agent**: Required. Set via `SEC_USER_AGENT` env var
- **Data Sources**: Submissions API (`data.sec.gov/submissions/`) and filing archives (`sec.gov/Archives/edgar/`)

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` and `src/extraction/segment_enricher.py` pass `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)

## Key Design Decisions

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives
5. **Table-aware matching**: Row structure parsing prevents cross-row keyword matches and prioritizes row headings
6. **Externalized configuration**: Metric keywords in `config/metric_keywords.yaml` - edit patterns without code changes

## Gold Standard Validation (Required for Keyword/Extraction Changes)

**When to Run**: Before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction/` modules
- `src/review/candidate_generator.py`
- `src/review/keyword_matching.py`

**Validation Workflow**:

1. **Quick Check** (during development):
   ```bash
   python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
   ```
   Review delta: positive = improvement, negative = regression.

2. **Formal Validation** (before commit):
   ```bash
   pytest -m gold_standard --gold-standard-mode=fresh
   ```
   All tests must pass. Regressions cause test failures.

3. **If Regression Detected**:
   - Investigate false negatives (missed metrics)
   - Check if trade-off is intentional (precision vs recall)
   - If intentional, document rationale in commit message
   - If unintentional, fix before committing

4. **Update Baseline** (after intentional changes):
   ```bash
   python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
   ```
   Commit the updated `data/gold_standard/baseline_metrics.json`.

**Key Metrics**:
- **Precision**: % of generated candidates that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

**Thresholds**:
- Regression tolerance: 1% (configurable via `--tolerance`)
- Tests fail if any metric drops below baseline - tolerance

## Documentation

See `docs/README.md` for complete index. Key: `docs/architecture/system-overview.md`, `docs/HUMAN_REVIEW_SYSTEM.md`

## Metric Lifecycle

See `docs/development/metric-lifecycle-process.md` for the authoritative guide on:
- Adding new metrics (patterns, database, mapping, UI)
- Deprecating metrics (preserving historical data)
- Removing metrics (when no production data exists)
- Metric ID naming conventions (`cm_` prefix)
- Dropdown category ordering (5 semantic categories)

## Task Execution Workflow

For medium+ tasks, use the structured worker prompt workflow:

- **Task tracking**: `docs/PROJECT_TASK_INVENTORY.md`
- **Prompt generator**: `docs/WORKER_PROMPT_GENERATOR.md`
- **Slash commands**: `/task-create [ID]`, `/task-run [ID]`

Skip the workflow for XS/S tasks (<2 hours) - code directly.

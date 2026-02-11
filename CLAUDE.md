# CLAUDE.md

## Environment

Always use `python3` instead of `python` in all scripts, hooks, and subprocess calls. This project only has `python3` available.

## Git Workflow

Before creating a new PR, always check if one already exists for the current branch using `gh pr list --head <branch-name>`. Update existing PRs instead of creating duplicates.

When committing changes, use `git status` first and only stage the specific files related to the current task. Never use `git add .` or `git add -A` without reviewing what's staged. Use `git add <specific-files>` instead.

Always work in the correct worktree for the branch you're targeting. Run `git worktree list` if unsure which directory to use.

Never delete branches that are checked out in worktrees. Run `git worktree list` first to verify a branch isn't in use before deleting it.

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py (PostgreSQL), sec_client.py (SEC EDGAR API)
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction (V1 - production)
├── extraction_v2/  # V2 pipeline (production-ready)
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
mypy src/review/ src/extraction/segment_enricher.py --strict  # Type checking
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

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `review_candidates`, `review_decisions`. Schema files in `sql/` (00-09). V2 tables: `v2_documents`, `v2_segments`, `v2_metric_facts`.

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` passes `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)
- **Database integration tests**: 1) Use correct ID types (UUID vs bigint) matching schema, 2) Include all required fields (sec_html_url, currency, metric IDs), 3) Use Decimal type for financial comparisons
- **Pre-commit requirement**: After implementing code changes, always run the full test suite (`pytest`) before committing. All tests must pass before push.

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
- `testing.md` - Loaded when editing `tests/**`
- `gold-standard.md` - Loaded when working with gold standard validation

## Available Commands

Use these slash commands for workflows:
- `/task-create [ID]` - Create a worker prompt for a task
- `/task-run [ID]` - Execute an existing worker prompt
- `/ralph [mode]` - Start Ralph Loop for autonomous execution
- `/metric-lifecycle` - Guide for adding/removing metrics

## Session Approach (MANDATORY)

BEFORE planning or implementing ANY task, you MUST:
1. Classify the task against the table below
2. State which execution approach you will use and why
3. Use the matched workflow — do NOT default to interactive when a structured workflow applies

| Task characteristics | Required approach |
|---|---|
| Single file, <3 changes | Interactive session |
| Multi-file, defined acceptance criteria | `/ralph develop --isolated` |
| Investigation/debugging | `/ralph analyze`, then `/ralph implement` |
| Extraction code + keyword changes | `/ralph develop` + gold-standard-validator agent |
| Large refactor (>10 files) | Team: implementer + test-runner + reviewer |
| Bulk extraction or validation | `/ralph extract` or `/ralph validate` |

- **Escalation rule (ENFORCED)**: If an interactive session reaches 5+ commits, STOP and switch to Ralph.
- **Freshness rule (ENFORCED)**: After any session with 3+ commits, update `ops/ITERATION_CONTEXT.md`.

Skipping methodology selection is a blocking error. State your choice before proceeding.

## Extraction Team Workflow

For changes to extraction code, keyword config, or FP rules, use the 2-agent pattern:

1. **Create team**: `TeamCreate` with `extraction-implementer` + `gold-standard-validator`
2. **Structure tasks**: Alternate implement → validate tasks with `blockedBy` dependencies
3. **Implementer** makes changes, self-tests, marks task complete
4. **Validator** runs gold standard, reports regressions, blocks merge if scores drop

Use this pattern for: keyword changes, classifier logic, FP filter rules, new gold standard filings.

Agent definitions: `.claude/agents/extraction-implementer.md`, `.claude/agents/gold-standard-validator.md`

## Gold Standard Validation

**Required** when modifying extraction code or keyword config:
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```
See `.claude/rules/gold-standard.md` for full workflow (auto-loaded when relevant).

## V2 Extraction Pipeline

When working on the V2 pipeline, always operate in the v2-rewrite worktree directory, not the main working directory. Check `git worktree list` if unsure.

The V2 pipeline (`src/extraction_v2/`) is a ground-up redesign with key improvements:
- **10x faster parsing** via lxml (vs BeautifulSoup)
- **Stable XPath locators** for every source element
- **Full table reconstruction** with header_path/stub_path binding
- **Image/OCR integration** for chart extraction
- **EvidencePack** with highlighted HTML and context

**Usage:**
```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(
    enable_image_extraction=True,
    min_confidence_auto_accept=0.90,
)
pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)

print(f"Extracted {result.fact_count} facts in {result.total_duration_ms}ms")
for fact in result.facts:
    print(f"  {fact.canonical_metric_id}: {fact.value} ({fact.confidence:.1%})")
```

**V2 vs V1 Comparison:**
```bash
python scripts/benchmark_v1_v2.py --filings slack samsara
```

See `docs/V2_MIGRATION_GUIDE.md` for full migration documentation and `docs/V2_IMPLEMENTATION_ROADMAP.md` for the complete implementation roadmap (all 13 phases complete).

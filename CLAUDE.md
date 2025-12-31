# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py (PostgreSQL), sec_client.py (SEC EDGAR API), validation.py
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction: html_segmenter, metric_classifier, keyword_config, value_extractor, segment_enricher, cohort_chart_detector
├── review/         # Human review: candidate_generator, pattern_analyzer, rule_applicator, table_structure
├── web/            # Flask app: routes/, templates/, static/
└── llm/            # OpenAI integration: openai_client.py, prompts.py
config/
└── metric_keywords.yaml  # Externalized metric keyword patterns (editable without code changes)
```

**Pipeline:** UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer → Database

**Review system config:** See `src/review/config.py` for `CandidateGenerationConfig` and presets (`get_high_precision_config()`, etc.)

## Database Schema

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `filing_metric_incidence`, `review_candidates`, `review_decisions`, `learned_patterns`. Schema files in `sql/` (01-07).

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

Use ast-grep for structural code searches. Prefer ast-grep over grep/ripgrep when:
- Searching for function/class definitions or calls
- Finding specific code patterns (e.g., all methods with certain decorators)
- Refactoring: locating all usages of a pattern

**Examples:**
```bash
# Find all function definitions
ast-grep run --pattern 'def $FUNC($$$ARGS):' --lang python src/

# Find all class definitions
ast-grep run --pattern 'class $NAME:' --lang python src/

# Find all uses of a specific function
ast-grep run --pattern 'extract_metrics($$$)' --lang python .

# Find decorated functions
ast-grep run --pattern '@pytest.fixture
def $NAME($$$):' --lang python tests/

# Find try/except blocks
ast-grep run --pattern 'try:
    $$$BODY
except $EXC:
    $$$HANDLER' --lang python src/
```

**Configuration:** `sgconfig.yml` in project root. Custom rules in `ast-grep-rules/`.

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
6. **Tiered richness scoring** (2025-12-17): Usage metrics (DAU/MAU/WAU) receive context-aware bonuses:
   - +1.0 for usage metrics with numeric values ("10 million daily active users")
   - +0.75 for usage keywords with definitions or metric context
   - +0.5 for basic usage keyword matches (backward compatible)
   - Similar tiered bonuses apply to definition flags based on high-value metric presence
7. **Enhanced date filtering** (2025-12-17): Comprehensive false positive filters eliminate years (1990-2100) and date components using:
   - 4-digit year detection
   - Date pattern matching ("January 31, 2019")
   - Temporal phrase recognition ("as of", "ended", "for the period", etc.)
   - Result: 100% elimination of date false positives in candidate generation
8. **Externalized keyword configuration** (2025-12-27): Metric keywords moved to `config/metric_keywords.yaml`:
   - Add/modify keyword patterns without code changes
   - YAML structure: patterns, exclusions, specific_patterns, required_context per metric
   - YAML is the authoritative source of truth (no hardcoded fallback)
   - Environment override: `METRIC_KEYWORDS_CONFIG=/path/to/custom.yaml`
   - Fails fast with clear error if YAML cannot be loaded
9. **Cohort chart image detection** (2025-12-29): Automated detection of cohort analysis charts in filings:
   - Segment-level detection via `segment_enricher._detect_cohort_chart_images()` (stores candidates in `extra_metadata`)
   - Filing-level detection via `cohort_chart_detector.py` (reads source HTML directly for standalone images)
   - Heuristic: "cohort" keyword within 1500 chars of `<img>` tags
   - Confidence scoring: base 0.6 + bonuses for chart keywords (0.15), retention context (0.10), multiple keywords (0.10)
   - Filters decorative images by size and naming patterns (icons, logos, bullets)
   - Use case: Identify high-value cohort analysis visualizations (ARR by cohort, LTV/CAC, retention curves)
10. **Context-gated revenue synonym metrics** (2025-12-30): Revenue synonyms require cohort/per-customer context:
    - GMV, TCV, ACV, Bookings, Billings only generate review candidates when context is present
    - Context keywords: cohort, vintage, per customer, per user, by account, customer-level, etc.
    - Proximity: context must appear within 1500 chars of keyword match
    - ARR/MRR NOT context-gated (inherently customer-related: "recurring" implies subscriptions)
    - Classification preserved: revenue synonyms still contribute to segment enrichment/richness scoring
    - Configuration: `required_context` in `config/metric_keywords.yaml` with YAML anchor sharing

## Documentation

See `docs/README.md` for complete index. Key: `docs/architecture/system-overview.md`, `docs/HUMAN_REVIEW_SYSTEM_PLAN.md`

## Task Execution Workflow

**IMPORTANT**: This project uses a structured worker prompt workflow for task execution.

### When to Use (Size-Based)

| Task Size | Time Estimate | Workflow Required? |
|-----------|---------------|-------------------|
| XS | <30 min | Optional (can code directly) |
| S | 30 min - 2 hr | Optional (recommended for multi-file changes) |
| M | 2-4 hr | **Required** |
| L | 4-8 hr | **Required** |
| XL | >8 hr | **Required** (consider decomposition) |

### Workflow Steps

1. **Generate Worker Prompt** - Use `docs/WORKER_PROMPT_GENERATOR.md` to create task packet
2. **Execute Task** - Follow the worker prompt requirements
3. **Run Verification** - Execute verification commands from prompt
4. **Critical Evaluation** - Review code quality, tests, architecture (see template v2.5)
5. **User Approval** - STOP and ask user before implementing improvements
6. **Generate Follow-Ups** - Create task suggestions for deferred improvements
7. **Complete Report** - Fill `docs/COMPLETION_REPORT_TEMPLATE.md`
8. **Commit & Push** - With task ID reference

### Key Files

- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.5) - Task prompt format
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.1) - Meta-prompt for generating prompts
- `docs/COMPLETION_REPORT_TEMPLATE.md` (v1.1) - Completion documentation format

### Quick Start

Use `/task` command to invoke the workflow, or for M/L/XL tasks, automatically follow this structure.

**Do NOT** jump directly to coding for M/L/XL tasks without creating a worker prompt first.

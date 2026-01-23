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

## Claude Code MCP Servers (Optional)

For browser automation when testing the Flask review UI:

```bash
claude mcp add --transport stdio playwright -- npx -y @playwright/mcp@latest
```

For GitHub issue/PR management:

```bash
claude mcp add github -- npx -y @anthropic-ai/mcp-github
```

This enables direct GitHub operations (create/close issues, manage PRs, update labels) without manual API calls.

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
11. **Cross-metric substring suppression** (2025-12-31): When keywords from different metrics overlap:
    - If one keyword text is a substring of another at overlapping positions, keep only the longer match
    - Example: "Paid Customers" suppressed by "Paid Customers > $100,000" when they overlap
    - Label-embedded values filtered: numbers following comparison operators (e.g., "> $100,000") are not extracted
    - Logs at INFO level with "CMS-1" prefix for production monitoring
    - **FOLLOW-UP NEEDED**: Greedy patterns in `metric_keywords.yaml` (line 254: `\bretention\s+rate[^.;]{0,50}\d+%`) can cause unexpected suppression. Consider constraining these patterns to reduce false matches.
12. **Metric ID alias system** (2026-01-01): Canonical metric IDs can have aliases for gold standard compatibility:
    - Aliases defined in `config/metric_keywords.yaml` under each metric's `aliases` field
    - Functions in `keyword_config.py`: `get_aliases()`, `resolve_to_canonical()`, `get_all_equivalent_ids()`, `metrics_are_equivalent()`
    - Used by `validate_against_gold_standard.py` for accurate precision/recall measurement
    - System always generates canonical IDs; aliases only used for comparison/validation
13. **Character offset computation removed** (2026-01-07): `char_start_offset` and `char_end_offset` fields are always NULL:
    - Removed `_compute_element_offsets()` from HTMLSegmenter (INV-1-FIX-v2)
    - Root cause: BeautifulSoup HTML normalization caused O(n*m) performance issues (~105s for large filings)
    - Impact: None - offset data was not used by any feature (review UI uses keyword text matching)
    - Alternative: Use `html_selector` (CSS selector) for source location if needed
    - DB columns retained for schema compatibility
14. **Customer count metric distinction** (2026-01-07, MET-1): Two semantically distinct customer count metrics:
    - `cm_customers_period_end`: Period-end stock count (total customers, paid customers, customer base)
    - `cm_active_customers_total`: Engagement-based count (active customers, active users, active accounts)
    - These are NOT aliases - they measure different things:
      - "We have 10,000 total customers" → `cm_customers_period_end`
      - "We have 8,000 active customers" → `cm_active_customers_total`
    - Both metrics exist in SQL with `status = 'active'`
    - METRIC_NAME_MAPPING in `value_extractor.py` routes LLM names to correct canonical ID
15. **Unit-type validation filtering** (2026-01-07): Candidate generation filters metric-unit mismatches:
    - `COUNT_ONLY_METRICS`: Customer counts must be plain integers (filters percentages, currencies)
    - `PERCENTAGE_ONLY_METRICS`: Retention/churn rates must be percentages
    - `DOLLAR_ONLY_METRICS`: Revenue metrics (ARR, LTV, CAC) must be currency
    - Defined in `src/review/false_positive_filter.py`, applied in `candidate_generator.py:802-838`
    - Example: "146% retention" won't match `cm_large_customers_period_end` (expects count)
16. **Div-wrapped table deduplication** (2026-01-07): Tables inside `<div>` wrappers are now handled correctly:
    - Skip `<div>` elements that contain only a `<table>` (no additional text) - prevents duplicate extraction
    - Composite split tables (from divs with text + table) now get `[ROW]`/`[CELL]` markers
    - Fixes cross-row false positives where keywords from one table row matched numbers in another row
    - Implementation: `html_segmenter.py` lines 278-288 (skip logic), 883 (marker extraction), 922-927 (truncation path)
    - Test coverage: `TestDivOnlyTableSkip`, `TestCompositeSplitTableMarkers` in test_html_segmenter.py
17. **Post-number unit filtering** (2026-01-23): YAML exclusion patterns filter numbers followed by non-metric units:
    - Pattern: `\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:unit_words)\b` handles scale words ("million") and hyphenated words ("third-party")
    - `cm_daily_active_users`: Excludes "applications", "countries", "languages", "integrations"
    - `cm_customers_period_end`: Excludes "hours"
    - `cm_active_customers_total`: Excludes "hours", "countries", "languages"
    - `cm_new_customers_acquired`: Excludes "applications", "integrations"
    - Examples filtered: "450,000 third-party applications", "50 million hours", "150 countries"
    - Validated against gold standard: no regression on valid metrics like "88,000 Paid Customers"

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

1. **Check Task Inventory** - Review `docs/PROJECT_TASK_INVENTORY.md` for:
   - Task status, dependencies, and wave assignment
   - Blocked/blocking tasks to avoid conflicts
   - Parallel tasks that may modify same files
2. **Generate Worker Prompt** - Use `docs/WORKER_PROMPT_GENERATOR.md` to create task packet
3. **Execute Task** - Follow the worker prompt requirements
4. **Run Verification** - Execute verification commands from prompt
5. **Gold Standard Validation** - **Required** if task modified any of:
   - `config/metric_keywords.yaml`
   - `src/extraction/` modules
   - `src/review/candidate_generator.py`
   - `src/review/keyword_matching.py`

   Run: `pytest -m gold_standard --gold-standard-mode=fresh -v`
   See "Gold Standard Validation" section above for full workflow.
6. **Critical Evaluation** - Review code quality, tests, architecture (see template v2.5)
7. **User Approval** - STOP and ask user before implementing improvements
8. **Generate Follow-Ups** - Create task suggestions for deferred improvements
9. **Complete Report** - Fill `docs/COMPLETION_REPORT_TEMPLATE.md`
10. **Update Task Inventory** - Mark task complete in `docs/PROJECT_TASK_INVENTORY.md`
11. **Commit & Push** - With task ID reference

### Key Files

- `docs/PROJECT_TASK_INVENTORY.md` - Central task tracking (status, dependencies, waves)
- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.6) - Task prompt format
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.1) - Meta-prompt for generating prompts
- `docs/COMPLETION_REPORT_TEMPLATE.md` (v1.1) - Completion documentation format

### Quick Start

Use these slash commands for the task workflow:
- `/task-create [ID]` - Generate a worker prompt and save it (does NOT execute)
- `/task-run [ID]` - Execute an existing worker prompt with auto-context loading (e.g., `/task-run HRV-17`)

**Do NOT** jump directly to coding for M/L/XL tasks without creating a worker prompt first.

### Additional Workflow Tools

- **Lightweight Template**: `docs/WORKER_PROMPT_TEMPLATE_LITE.md` - Use for XS/S tasks (<2 hours)
- **GitHub Sync**: `python scripts/sync_github_issues.py --check` - Compare task inventory with GitHub issues
- **Doc Maintenance**: `docs/DOCUMENTATION_MAINTENANCE.md` - Quarterly cleanup checklist
- **Project Settings**: `.claude/settings.json` - Pre-approved tool permissions for this project

## Ralph Loop Autonomous Execution

Ralph Loop enables autonomous task execution with fresh context per iteration, avoiding "context rot" in long-running operations.

### When to Use Ralph vs Interactive

| Scenario | Use Ralph | Use Interactive (`/task-run`) |
|----------|-----------|-------------------------------|
| Overnight bulk work | Yes | No |
| Single task, present | No | Yes |
| M/L/XL tasks, stepping away | Yes | No |
| Requires human judgment | No | Yes |
| Investigation/analysis | Yes (`analyze` mode) | Sometimes |
| Series of bug fixes | Yes (`implement` mode) | Sometimes |
| Coverage improvement | Yes (`test` mode) | Sometimes |

### Ralph Modes

| Mode | Purpose | Command |
|------|---------|---------|
| `develop` | Execute Worker Prompt task | `./ops/loop.sh develop [max_iter] [--isolated]` |
| `refactor` | Safe refactoring with test preservation | `./ops/loop.sh refactor` |
| `test` | Coverage improvement | `./ops/loop.sh test` |
| `analyze` | Investigation and root cause analysis | `./ops/loop.sh analyze` |
| `implement` | Fix implementation from analysis | `./ops/loop.sh implement` |
| `extract` | Bulk filing extraction | `./ops/loop.sh extract` |
| `validate` | Bulk validation | `./ops/loop.sh validate` |

### Branch Isolation

Ralph supports three isolation modes (third argument):

| Flag | Behavior | Use When |
|------|----------|----------|
| `--isolated` | Creates `ralph/[mode]-[date]-[id]` branch (default) | Overnight runs, risky changes |
| `--current` | Uses current branch (blocks main/master) | Supervised daytime work |
| `--yolo` | No branch protection | Expert use only |

### Starting Ralph for Overnight Work

```bash
# Create worker prompt (if not exists)
/task-create MET-15

# Start Ralph in background with logging
nohup ./ops/loop.sh develop 20 --isolated > ops/logs/ralph_$(date +%Y%m%d).log 2>&1 &

# Check progress in the morning
cat ops/DEVELOPMENT_PLAN.md
git log --oneline -20
```

### Guardrails

- **Pre-flight**: Tests must pass, no uncommitted changes
- **Branch isolation**: Configurable per run (default: `--isolated`)
- **Commit gate**: Tests must pass before each commit
- **3 consecutive errors**: Pauses for human review
- **Test regression**: Rolls back and pauses
- **>500 line diff**: Pauses for review
- **4 hour max runtime**: Stops gracefully
- **Protected files**: Never modifies `.env`, `*.pem`, schema files
- **Recovery points**: Git tag before each iteration

### Recovery

```bash
# List checkpoints
git tag | grep ralph-checkpoint

# Rollback to specific checkpoint
git reset --hard ralph-checkpoint-5

# View overnight changes
git diff main..HEAD
```

### Key Files

- `ops/loop.sh` - Main orchestrator
- `ops/PROMPT_[mode].md` - Mode-specific instructions
- `ops/[MODE]_PLAN.md` - Task checklists
- `ops/README.md` - Full Ralph documentation

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

For complete extraction/keyword logic history with implementation details, see `docs/architecture/extraction-decisions.md`.

**Core principles (always apply)**:
1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives
5. **Table-aware matching**: Row structure parsing with `[ROW]`/`[CELL]` markers prevents cross-row false positives

**Keyword configuration**: All patterns in `config/metric_keywords.yaml` (authoritative source, no hardcoded fallback)

**Customer metrics distinction**:
- `cm_customers_period_end`: Period-end stock count ("total customers", "paid customers")
- `cm_active_customers_total`: Engagement-based ("active customers", "active users") - NOT aliases

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

1. **Generate Worker Prompt** - Use `docs/WORKER_PROMPT_GENERATOR.md` or `docs/WORKER_PROMPT_RALPH.md` (streamlined for Ralph)
2. **Execute Task** - Follow the worker prompt requirements
3. **Run Verification** - Execute verification commands from prompt
4. **Gold Standard Validation** - **Required** if task modified any of:
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

- `docs/WORKER_PROMPT_TEMPLATE.md` (v2.6) - Full task prompt format (complex/architectural tasks)
- `docs/WORKER_PROMPT_RALPH.md` - Streamlined template for Ralph autonomous execution
- `docs/WORKER_PROMPT_GENERATOR.md` (v1.1) - Meta-prompt for generating prompts
- `docs/archive/historical/PROJECT_TASK_INVENTORY.md` - Historical task tracking (archived)

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
- `ops/ITERATION_CONTEXT.md` - Handoff state between iterations (read first, update at end)
- `ops/[MODE]_PLAN.md` - Task checklists
- `ops/README.md` - Full Ralph documentation

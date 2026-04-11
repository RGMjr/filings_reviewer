# Powerup: Interactive Project Lessons

Discover the filings_reviewer system through quick interactive lessons. Each lesson teaches a key part of the project with live codebase walkthroughs.

## Usage

```
/powerup [lesson]
```

Without arguments, show the lesson menu. With a lesson name or number, jump directly to that lesson.

## Step 1: Show Lesson Menu

Present this menu using AskUserQuestion:

**Filings Reviewer Powerup**

| # | Lesson | Duration | What you'll learn |
|---|--------|----------|-------------------|
| 1 | **Pipeline** | ~5 min | How SEC filings flow from EDGAR to extracted metrics |
| 2 | **Keywords** | ~5 min | How `metric_keywords.yaml` drives extraction and how to add new metrics |
| 3 | **Gold Standard** | ~5 min | How to validate extraction quality and guard against regressions |
| 4 | **Review System** | ~5 min | How human review candidates are generated and scored |
| 5 | **Tier System** | ~3 min | Metric priority tiers and how they affect development decisions |
| 6 | **Project Commands** | ~3 min | Custom slash commands for common workflows |
| 7 | **Hooks & Rules** | ~3 min | Automatic safety checks that run as you work |
| 8 | **Testing** | ~3 min | Test strategy, coverage requirements, and CI checks |
| 9 | **Database** | ~5 min | Schema, migrations, and data access patterns |
| 10 | **Day-to-Day** | ~5 min | Common development workflows end to end |

If the user passed a lesson name or number as argument, skip the menu and go directly to that lesson.

## Step 2: Deliver the Selected Lesson

For each lesson, follow this pattern:
1. **Explain** the concept in 2-3 sentences
2. **Show** real code/config from the codebase (use Read to show actual files, not fabricated examples)
3. **Walk through** a concrete example
4. **Highlight** common pitfalls or gotchas
5. **Link** to relevant docs

---

### Lesson 1: Pipeline

**Goal:** Understand how SEC filings flow through the extraction pipeline.

1. Read and show the pipeline stages from `docs/architecture/extraction-pipeline.md` (first section)
2. Read `src/extraction_v2/pipeline.py` — show the main pipeline class and its `run()` or `process()` method signature
3. Walk through the stages:
   - **UniverseBuilder** → identifies S-1/F-1 filings from EDGAR
   - **FilingFetcher** → downloads filing HTML from SEC
   - **HTMLSegmenter** → splits filings into atomic segments (paragraphs, tables, footnotes)
   - **MetricClassifier** → keyword-based matching against `metric_keywords.yaml`
   - **SegmentEnricher** → adds context (surrounding text, table headers)
   - **ValueExtractor** → extracts numeric values with units/periods
   - **DefinitionExtractor** → extracts how companies define their metrics
   - **QualityScorer** → scores disclosure quality (0-3 scale)
4. Highlight: "Rule-based first, LLM second" — keyword matching handles 50-70% of metrics at $0; LLM is only called when rules can't resolve
5. Link: `docs/architecture/extraction-pipeline.md`, `docs/architecture/system-overview.md`

---

### Lesson 2: Keywords

**Goal:** Understand how `metric_keywords.yaml` drives extraction.

1. Read and show 2-3 metric entries from `config/metric_keywords.yaml` (e.g., `cm_customer_retention_rate`, `cm_customers_period_end`)
2. Explain the structure:
   - `primary`: words that signal this metric (triggers candidate generation)
   - `context`: words that must also appear nearby to confirm the match
   - `negative`: words that disqualify a match (false positive prevention)
3. Show a concrete example: how "net revenue retention" in filing text gets matched to `cm_net_revenue_retention`
4. Walk through adding a new metric using `/metric-lifecycle`
5. Highlight the PostToolUse hook: editing `metric_keywords.yaml` triggers a reminder to run gold standard validation
6. Link: `docs/development/metric-lifecycle-process.md`, `config/metric_keywords.yaml`

---

### Lesson 3: Gold Standard

**Goal:** Understand how gold standard validation prevents extraction regressions.

1. Read and show `src/gold_standard/` directory structure
2. Explain: gold standard = human-verified extraction results for ~15 companies; used as ground truth
3. Show the baseline file: read `tests/gold_standard/v2_baseline.json` and explain P/R/F1 metrics
4. Walk through running validation:
   ```
   pytest -m gold_standard --gold-standard-mode=fresh -v
   ```
5. Explain the regression guard: baseline metrics are compared; regressions in Tier 1 metrics are blockers
6. Show the golden set CSV: read first few lines of the authoritative CSV file (search for `golden_set_*.csv`)
7. Highlight: Tier 1 regressions block commits; Tier 2 regressions are acceptable if Tier 1 improves
8. Link: `docs/operations/gold-standard-runbook.md`, `docs/GOLD_STANDARD_SPECIFICATION.md`

---

### Lesson 4: Review System

**Goal:** Understand how human review candidates are generated and how feedback loops work.

1. Read `src/review/` directory structure and show key files
2. Explain the review pipeline:
   - **CandidateGenerator** → surfaces uncertain or interesting extraction results for human review
   - **FeatureExtractor** → computes features for each candidate (confidence scores, context signals)
   - **ReviewRoutes** → web UI where humans accept/reject/correct extractions
   - **PatternAnalyzer** → finds patterns in human decisions
   - **RuleApplicator** → applies learned rules to future extractions
3. Show a review route from `src/web/` that handles review decisions
4. Highlight: the system learns from human feedback — patterns become automated rules
5. Link: `docs/HUMAN_REVIEW_SYSTEM.md`

---

### Lesson 5: Tier System

**Goal:** Understand metric priority tiers and how they affect decisions.

1. Read the tier definitions from CLAUDE.md (the "Metric Priority Tiers" section)
2. Show the authoritative tier config in `config/metric_keywords.yaml` (search for tier markers)
3. Explain:
   - **Tier 1 (must-not-miss):** Cohorted data, retention, LTV/CAC, revenue concentration — these are the most analytically valuable
   - **Tier 2 (nice-to-have):** Customer counts, engagement, unit economics, ARR
4. Walk through how tiers affect development:
   - Tier 1 gold standard regression = blocker, must fix before commit
   - Tier 2 regression = acceptable trade-off if Tier 1 improves
   - Extraction improvements should target Tier 1 recall gaps first
5. Link: CLAUDE.md, `config/metric_keywords.yaml`

---

### Lesson 6: Project Commands

**Goal:** Know the custom slash commands and when to use each.

1. List all commands from `.claude/commands/` directory
2. For each, read the first 5-10 lines to get the purpose
3. Walk through the most important ones:
   - `/task-create [ID]` — generate a structured worker prompt (does NOT execute)
   - `/task-run [ID]` — execute an existing worker prompt with approval gates
   - `/ralph [mode]` — autonomous execution loop (for overnight runs)
   - `/metric-lifecycle` — guided metric add/deprecate/remove
   - `/ci-fix` — autonomous lint/type/test fix loop
   - `/merge-check` — thorough pre-merge assessment
   - `/plan-execute` — parallel multi-phase execution
   - `/doc-audit` — documentation freshness check
4. Highlight: `/task-create` generates, `/task-run` executes — they're separate on purpose
5. Link: `docs/README.md` (Slash Commands section)

---

### Lesson 7: Hooks & Rules

**Goal:** Understand automatic safety checks that run as you work.

1. Read and show `.claude/settings.json` — focus on the `hooks` section
2. Explain each hook:
   - **PostToolUse on metric_keywords.yaml** → reminds you to run gold standard validation
   - **PostToolUse on src/extraction** → same reminder for extraction code changes
   - **PostToolUse on sql/** → reminds about migration numbering and FK ordering
   - **PostToolUse on *.py** → runs `ruff check` automatically after Python file edits
   - **Stop hook** → checks git state before session ends
3. Read and show `.claude/rules/` directory — explain that rules auto-load based on file paths being edited
4. Show one rule file (e.g., `.claude/rules/extraction.md`) to demonstrate the concept
5. Highlight: hooks fire automatically — you don't need to remember to run lint or validation checks
6. Link: `.claude/settings.json`, `.claude/rules/`

---

### Lesson 8: Testing

**Goal:** Understand test strategy, coverage requirements, and CI pipeline.

1. Show test directory structure: `ls tests/`
2. Explain the testing tiers:
   - **Unit tests** (`tests/unit/`): fast, no external dependencies
   - **Gold standard tests** (`tests/gold_standard/`): extraction accuracy regression guard
3. Show key testing commands:
   ```bash
   pytest -v                             # All tests
   pytest -x -q                          # Quick check (stop on first failure)
   pytest --cov=src --cov-report=html    # Coverage report
   pytest -m gold_standard --gold-standard-mode=fresh -v  # Gold standard
   ```
4. Explain coverage requirements: 75% minimum enforced, currently at 87%
5. Explain the pre-commit rule: run `pytest -x -q` when staged changes include code files
6. Highlight: pre-existing test failures — check `git stash` to verify a failure predates your changes
7. Link: `docs/development/testing.md`

---

### Lesson 9: Database

**Goal:** Understand the schema, migrations, and data access patterns.

1. Show the `sql/` directory structure (list migration files)
2. Explain key tables:
   - `companies` — SEC registrants
   - `filings` — S-1/F-1 filings metadata
   - `source_segments` — atomic content units from filings
   - `metric_values` — extracted numeric values
   - `metric_definitions` — how companies define their metrics
   - `review_candidates` — items queued for human review
   - `review_decisions` — human reviewer judgments
3. Show the data model from `docs/architecture/data-model.md` (key sections)
4. Explain migration conventions:
   - Sequential numbering (00-21), no gaps or duplicates
   - FK references only to tables from earlier migrations
   - `scripts/apply_all_migrations.py` applies them all in order
5. Highlight: the PostToolUse hook on `sql/` reminds about migration ordering
6. Link: `docs/architecture/data-model.md`, `sql/`

---

### Lesson 10: Day-to-Day

**Goal:** Walk through common development workflows end to end.

1. **Adding a keyword pattern:**
   - Edit `config/metric_keywords.yaml`
   - Run gold standard validation
   - Check for Tier 1 regressions
   - Commit with `/commit`

2. **Investigating a false positive:**
   - Use pipeline-debugger agent to trace the extraction
   - Check which keyword pattern matched
   - Add a `negative` pattern or FP rule
   - Validate with gold standard

3. **Adding a new metric end-to-end:**
   - Use `/metric-lifecycle` for guidance
   - Add to `metric_keywords.yaml`
   - Add database definition
   - Update UI mapping
   - Add gold standard entries
   - Validate

4. **Fixing a CI failure:**
   - Use `/ci-fix` for automated lint/type/test fixing
   - Or manually: `ruff check`, `mypy`, `pytest`

5. **Running a large task overnight:**
   - Create worker prompt: `/task-create TASK-ID`
   - Review the generated prompt
   - Start Ralph: `/ralph develop TASK-ID --isolated`

Show relevant file paths and commands for each workflow.

---

## Step 3: After Lesson Completion

After delivering a lesson, ask:

> "Want to try another lesson, or dive deeper into anything covered here?"

If the user picks another lesson, deliver it. If they want to go deeper, explore the specific topic interactively using Read/Grep on the relevant files.

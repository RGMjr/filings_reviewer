# Project Tutorial: Interactive Lessons

Discover the filings_reviewer system through interactive lessons with live codebase walkthroughs.

## Usage

```
/project-tutorial [lesson]
```

Without arguments, show the lesson menu. With a lesson name or number, jump directly to that lesson.

## Step 1: Show Lesson Menu

Display this table directly (do NOT use AskUserQuestion):

| # | Lesson | What you'll learn |
|---|--------|-------------------|
| 1 | **Extraction Pipeline** | How V2Pipeline turns filing HTML into structured MetricFacts |
| 2 | **Keywords & Candidates** | How `metric_keywords.yaml` drives candidate generation |
| 3 | **Quality Gates** | Gold standard validation, metric tiers, and regression policy |
| 4 | **Review System** | Human review candidates, feedback loops, learned rules |
| 5 | **Hooks, Rules & Testing** | Automatic safety checks, test strategy, CI pipeline |
| 6 | **Database & Migrations** | Schema, migration conventions, data access patterns |
| 7 | **Commands & Workflows** | Custom slash commands and common day-to-day patterns |

If the user passed a lesson name or number as argument, skip the menu and go directly to that lesson.

## Step 2: Deliver the Selected Lesson

For each lesson, follow this pattern:
1. **Explain** the concept in 2-3 sentences
2. **Read** the specified files and explain what you find (never hardcode facts — always read current values)
3. **Walk through** a concrete example
4. **Highlight** common pitfalls
5. **Link** to relevant docs

**Critical rule:** Do NOT recite the lesson notes below verbatim. Read the actual files, report current values, and explain in your own words based on what the code says now.

---

### Lesson 1: Extraction Pipeline

**Goal:** Understand how V2Pipeline processes a filing HTML into MetricFacts.

**Read these files and explain what you find:**
1. `src/extraction_v2/pipeline.py` — read the module docstring (pipeline stage list), `PipelineConfig` class, `_setup_stages()` method, and `process()` method
2. `docs/architecture/extraction-pipeline.md` — read the V2 Pipeline Overview section and stage diagram

**Walk through:** Trace what happens when a filing contains "net revenue retention rate of 130%" — which stages touch it and what each produces.

**Highlight:**
- The pipeline takes an HTML file as input. Universe building and filing fetching are separate upstream systems, not pipeline stages.
- Four stages are critical (pipeline halts if they fail) — read the `process()` method to identify which ones.
- Three document-type configs exist (`PipelineConfig`, `.for_transcript()`, `.for_presentation()`) — read and compare them.

**Docs:** `docs/architecture/extraction-pipeline.md`, `docs/architecture/system-overview.md`

---

### Lesson 2: Keywords & Candidates

**Goal:** Understand how `metric_keywords.yaml` drives candidate generation.

**Read these files and explain what you find:**
1. `config/metric_keywords.yaml` — show 2-3 complete metric entries (pick one Tier 1 and one Tier 2)
2. `src/extraction_v2/stages/candidate_generation.py` — read the main class and its matching logic

**Walk through:** Pick a metric from the YAML, show its `primary`/`context`/`negative` fields, and trace how text containing those keywords becomes a MetricCandidate.

**Highlight:**
- Editing this file triggers a PostToolUse hook reminding you to run gold standard validation
- The `/metric-lifecycle` command guides adding/deprecating metrics

**Docs:** `docs/development/metric-lifecycle-process.md`, `config/metric_keywords.yaml`

---

### Lesson 3: Quality Gates

**Goal:** Understand gold standard validation, metric tiers, and regression policy.

**Read these files and explain what you find:**
1. `tests/gold_standard/` — list directory contents, then read the baseline JSON file(s) and report current P/R/F1 numbers
2. Search for `golden_set_*.csv` — read the first 10 lines to show the format
3. `CLAUDE.md` — read the "Metric Priority Tiers" section
4. `config/metric_keywords.yaml` — search for `tier:` fields and show examples

**Walk through:** Explain the validation command (`python3 -m src.gold_standard.v2_validator`), what it compares against, and what happens when a regression is detected.

**Highlight:**
- Tier 1 regression = blocker, must fix before commit. Tier 2 regression = acceptable if Tier 1 improves.
- Read the tier lists from CLAUDE.md rather than reciting them — they may have changed.

**Docs:** `docs/operations/gold-standard-runbook.md`, `docs/GOLD_STANDARD_SPECIFICATION.md`

---

### Lesson 4: Review System

**Goal:** Understand how human review candidates are generated and how feedback loops improve extraction.

**Read these files and explain what you find:**
1. `src/review/` — list directory contents, then read the module-level docstrings of key files
2. `src/web/` — find the review-related route file(s) and show how review decisions are handled

**Walk through:** Trace the lifecycle of an uncertain extraction: how it becomes a review candidate, what a human reviewer sees, and how their decision feeds back into the system.

**Highlight:**
- PatternAnalyzer finds patterns in human decisions; RuleApplicator turns them into automated rules
- The confidence thresholds in `PipelineConfig` (`min_confidence_auto_accept`, `max_confidence_auto_reject`) control what goes to review

**Docs:** `docs/HUMAN_REVIEW_SYSTEM.md`

---

### Lesson 5: Hooks, Rules & Testing

**Goal:** Understand the automatic safety checks and test infrastructure.

**Read these files and explain what you find:**
1. `.claude/settings.json` — read the `hooks` section and explain each hook
2. `.claude/rules/` — list the directory, then read one rule file to show the concept
3. `tests/` — list the directory structure
4. `docs/development/testing.md` — read the coverage requirements and test categories

**Walk through:** Show what happens when you edit a `.py` file (ruff auto-runs), edit `metric_keywords.yaml` (validation reminder), or edit `sql/` (migration ordering reminder).

**Highlight:**
- Read current coverage threshold from `.claude/settings.json` or CLAUDE.md — don't assume a number
- Pre-existing test failures: `git stash && pytest <test> -x -q && git stash pop` to verify a failure predates your changes

**Docs:** `docs/development/testing.md`, `.claude/settings.json`

---

### Lesson 6: Database & Migrations

**Goal:** Understand the schema, migration conventions, and data access patterns.

**Read these files and explain what you find:**
1. `sql/` — list the directory to show migration files and their numbering
2. Read the first migration file to show the schema foundation
3. `docs/architecture/data-model.md` — read the key tables section and relationship diagram

**Walk through:** Trace the data path from a filing HTML to queryable metric values — which tables get written and in what order.

**Highlight:**
- Sequential numbering, no gaps or duplicates. FK references only to tables from earlier migrations.
- The PostToolUse hook on `sql/` reminds about migration ordering
- `scripts/apply_all_migrations.py` applies them all in canonical order

**Docs:** `docs/architecture/data-model.md`, `sql/`

---

### Lesson 7: Commands & Workflows

**Goal:** Know the custom slash commands and common development patterns.

**Read these files and explain what you find:**
1. `.claude/commands/` — list all files, then read the first 5 lines of each to get purposes
2. `.claude/agents/` — list available specialized agents

**Walk through these common workflows** (show relevant commands and file paths for each):
- Adding a keyword pattern → validate → commit
- Investigating a false positive → trace → fix → validate
- Adding a new metric end-to-end (point to `/metric-lifecycle`)
- Fixing CI failures (point to `/ci-fix`)
- Running a large task overnight (point to `/task-create` → `/ralph`)

**Docs:** `docs/README.md` (Slash Commands section)

---

## Step 3: After Lesson Completion

After delivering a lesson, ask:

> "Want to try another lesson, or dive deeper into anything covered here?"

If they pick another lesson, deliver it. If they want to go deeper, explore interactively.

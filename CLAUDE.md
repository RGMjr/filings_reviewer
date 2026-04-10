# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

Source lives in `src/` (infra, universe, filing_fetcher, extraction_v2, review, shared, web, llm, gold_standard). Config in `config/metric_keywords.yaml`. See `docs/README.md` for full index.

**Pipeline (V2):** UniverseBuilder → FilingFetcher → V2Pipeline → V2PersistenceAdapter → V2QualityScorer → Database

## Key Commands

```bash
uv pip install -r requirements.txt # Install dependencies
pytest -v                          # Run all tests
pytest --cov=src --cov-report=html # Run with coverage
black src/ tests/                  # Format code
ruff check src/ tests/             # Lint
mypy src/review/ --strict          # Type checking
```

## Database

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `review_candidates`, `review_decisions`. Schema files in `sql/` (00-21). See `.claude/rules/infrastructure.md` when editing infra, Docker, or requirements files.

## Testing Standards

- **Coverage**: 75% minimum (enforced)
- **Type safety**: `src/review/` passes `mypy --strict`
- **Before committing**: Run `pytest -x -q` when staged changes include code files (`src/`, `tests/`, `scripts/`, `config/`, `sql/`, `pyproject.toml`, `requirements.txt`). Docs-only and `.claude/`-only commits may skip lint and tests. If fixing one failure breaks others, continue iterating until all pass in a single run before committing.
- **Pre-existing failures**: When a test fails during implementation, check whether it was already failing before your changes (`git stash && pytest <failing_test> -x -q && git stash pop`). Do not spend time debugging failures that predate the current work — note them and move on.

## Metric Priority Tiers

Metrics are classified into importance tiers based on analytical value. These tiers govern regression policy, extraction prioritization, and gold standard coverage priorities.

**Tier 1 (must-not-miss):** Cohorted data, retention, LTV/CAC, revenue concentration.
- `cm_customer_retention_rate`, `cm_net_revenue_retention`, `cm_gross_revenue_retention`
- `cm_revenue_by_cohort`, `cm_transactions_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`
- `cm_expansion_revenue` (cohorted products owned/enrolled)
- `cm_revenue_concentration`
- `cm_lifetime_value_per_customer`, `cm_customer_acquisition_cost`, `cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`

**Tier 2 (nice-to-have):** Customer counts, engagement, unit economics, ARR.
- All other `cm_*` metrics (customer counts, MAU/DAU, ARPU, ARR, AOV, etc.)

**Rules:**
- Tier 1 regression in gold standard validation = blocker, must fix before commit
- Tier 2 regression = acceptable trade-off if Tier 1 improves; note in commit message
- Extraction improvements (keywords, FP rules, value binding) should prioritize Tier 1 recall gaps first
- Gold standard coverage expansion should target Tier 1 metrics with low coverage
- Tier definitions live in `config/metric_keywords.yaml` (authoritative) and `src/gold_standard/v2_validator.py` (runtime)

## Core Design Principles

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives

## Implementation Rules

- Execute ONLY the steps specified. Do not expand scope, fix adjacent issues, or refactor beyond what was asked.
- When given a numbered plan, implement exactly those items. Do not add extra steps or address anything not listed.
- If you notice a related issue while working, call it out to the user rather than silently fixing it.

## Pre-Implementation Gate

For any change touching 3+ files or involving extraction/config/migration changes, complete this pre-flight checklist before writing code:

1. **ASSUMPTION AUDIT**: List every assumption in the plan. For each one, run a command (Read/Grep/Bash) to verify it against the current codebase state. Flag any stale or incorrect assumptions.
2. **SCOPE CHECK**: Confirm the plan only touches what was requested. List any out-of-scope changes and remove them.
3. **RULES COMPLIANCE**: Re-read CLAUDE.md and verify every planned action complies. Flag violations.
4. **RISK ASSESSMENT**: Check shared imports, migration ordering, and tests that depend on changed behavior. What could this break?
5. **MINIMAL PATH**: Identify the smallest set of changes that achieves the goal.

Show the completed checklist and get user approval before proceeding with implementation.

## Planning Discipline

- When self-correcting a plan, limit to 2 revision cycles. If still uncertain after 2 revisions, present the remaining options to the user rather than continuing to iterate.

## Git Operations

- Before any force-push, force-merge, rebase, or reset --hard: show the exact command, show current branch/HEAD state, and wait for explicit user confirmation ("yes" — not a number, not ambiguous input).
- Never interpret ambiguous input as approval for destructive git operations.
- Never use `git add -A` or `git add .` without explicit user instruction. Stage specific files by name.
- When asked to commit (any phrasing: "commit", "commit this", "commit and push", etc.), execute the `/commit` skill directly. Do not enter plan mode or ask clarifying questions — the skill handles all validation steps.

## Code Review / Audits

- When performing merge readiness assessments or code audits, do a thorough deep pass the first time. Do not produce superficial reports.
- Always check: CI status on the branch, migration file registration and ordering, import statements in changed files.
- Dropped imports and empty regex patterns from config moves are common failure modes — check for these explicitly.

## Shell Commands

- For multi-line shell commands, use heredocs or chain with `&&` / `;` on a single line.
- Do not use bare newlines between commands — they break in zsh.

## Planning Rules

- Every plan must include a **Documentation** step: identify docs that need updating to reflect the planned changes (e.g., `docs/`, CLAUDE.md, README, inline comments) and include explicit update actions. If no docs are affected, state that explicitly in the plan.

## Compact Instructions

When compacting, preserve: modified file paths, current test/gold-standard validation status, extraction pipeline decisions made this session, and any active task checklist.

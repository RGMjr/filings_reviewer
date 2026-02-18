# CLAUDE.md

## Environment

Always use `python3` instead of `python` in all scripts, hooks, and subprocess calls. This project only has `python3` available.

## Git Workflow

Before creating a new PR, always check if one already exists for the current branch using `gh pr list --head <branch-name>`. Update existing PRs instead of creating duplicates.

When committing changes, use `git status` first and only stage the specific files related to the current task. Never use `git add .` or `git add -A` without reviewing what's staged. Use `git add <specific-files>` instead.

Always work in the correct worktree for the branch you're targeting. Run `git worktree list` if unsure which directory to use. Never delete branches that are checked out in worktrees.

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Core Design Principles

1. **Rule-based first, LLM second**: Keyword matching before expensive LLM calls
2. **Provenance tracking**: Every extracted value links to source segment
3. **Idempotent operations**: Re-running any stage is safe (upserts)
4. **Conservative classification**: "Require BOTH" signals to minimize false positives

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` passes `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)
- **Pre-commit requirement**: Run full test suite (`pytest`) before committing. All tests must pass.

## Context-Specific Rules

Claude Code loads path-specific rules automatically from `.claude/rules/`:
- `extraction.md` - Loaded when editing `src/extraction/**` or `config/metric_keywords.yaml`
- `testing.md` - Loaded when editing `tests/**`
- `gold-standard.md` - Loaded when working with gold standard validation

## Available Commands

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

See `docs/V2_MIGRATION_GUIDE.md` for full migration documentation.

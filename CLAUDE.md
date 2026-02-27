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
- `docs.md` - Loaded when editing `docs/**`; defines canonical folder structure and placement rules

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

See `docs/V2_MIGRATION_GUIDE.md` for full migration documentation and `docs/V2_IMPLEMENTATION_ROADMAP.md` for the complete implementation roadmap (all 13 phases complete).

## Beyond SEC: Transcript & Presentation Support

**Branch:** `earnings-call-exploration` (worktree: `filings_reviewer_beyond_sec`)
**Status:** Phase A complete (12/12 ACs), Phase A+ in progress
**Design doc:** `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md`

The V2 pipeline has been extended to extract customer metrics from earnings call transcripts and investor presentations. Phase A is complete: all 12 acceptance criteria met, with R=65.9%, P=38.4%, F1=48.5% on the consolidated gold standard (94 annotations, 16 files). The original spike baseline was 22.1% recall / 63.0% precision on 77 annotated metrics.

**Document-type-aware config (implemented):**
```python
# Transcript processing — wider proximity, relaxed FP filter
config = PipelineConfig.for_transcript()

# Presentation processing — images enabled, relaxed FP filter
config = PipelineConfig.for_presentation()

# SEC filings — default behavior (unchanged)
config = PipelineConfig()
```

**Phase A (complete):** Value binding tuning, FP filter relaxation, period inference patterns, transcript converter, HuggingFace source, schema migration — all 12 ACs met. Achieved R=65.9% (target: ≥50%) on consolidated gold standard. See `ops/DEVELOPMENT_PLAN.md` for full AC list.

**Phase A+ (in progress):** Precision hardening and recall improvements beyond the Phase A target. Current focus: PYPL $-prefix transcript bug, Q&A section filtering, remaining keyword gaps (META family-of-apps, ADSK vocabulary). Target: R≥65%, P≥70%, F1≥67%.

**Spike scripts:**
- `scripts/spike/collect_samples.py` — HuggingFace dataset downloader
- `scripts/spike/convert_transcript_to_html.py` — text-to-HTML converter
- `scripts/spike/run_poc.py` — pipeline POC runner

**Spike data:** `data/spike_samples/` (22 transcripts, 77 annotations), `data/spike_results/` (per-file results)

**Gold standard:** `data/transcript_gold_standard/` (per-filing `*_reviewed.csv`, 94 annotations, 16 files). Run `scripts/merge_transcript_annotations.py` to consolidate before benchmarking. Benchmark script: `scripts/validate_transcript_extraction.py`.

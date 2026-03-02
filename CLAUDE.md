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
| Non-extraction multi-file changes | `dev-implementer` agent or `/ralph develop` |
| Investigation/debugging | `/ralph analyze`, then `/ralph implement` |
| Extraction code + keyword changes | `/ralph develop` + gold-standard-validator agent |
| Large refactor (>10 files) | Team: implementer + test-runner + reviewer |
| Bulk extraction or validation | `/ralph extract` or `/ralph validate` |

- **Escalation rule (ENFORCED)**: If an interactive session reaches 5+ commits, STOP and switch to Ralph.
- **Freshness rule (ENFORCED)**: After any session with 3+ commits, update `ops/ITERATION_CONTEXT.md`.

Skipping methodology selection is a blocking error. State your choice before proceeding.

## Extraction Team Workflow

For changes to extraction code, keyword config, or FP rules, use the multi-agent pattern:

1. **Create team**: `TeamCreate` with `extraction-implementer` + `keyword-config-checker` + `gold-standard-validator` (+ `pipeline-debugger` if regression expected)
2. **Structure tasks**: implement → check keywords → validate gold standard (with `blockedBy` dependencies)
3. **Implementer** makes changes, self-tests, marks task complete
4. **Keyword checker** validates regex compilation, pattern overlaps, and REQUIRE_BOTH logic (fast, seconds)
5. **Validator** runs gold standard, reports regressions, blocks merge if scores drop
6. **On regression**: Add `pipeline-debugger` task to trace the root cause through V2 stages, then loop back to implementer

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
**Status:** Phase A complete (12/12 ACs), Phase A+ complete (all targets met), Phase B complete, Phase C complete (M1-M4, M6; M5 deferred)
**Design doc:** `docs/analysis/spike/BEYOND_SEC_DESIGN_DOCUMENT.md`

The V2 pipeline has been extended to extract customer metrics from earnings call transcripts and investor presentations. Current transcript benchmark: R=75.8%, P=74.2%, F1=75.0% (91 annotations, 20 files, 2026-03-02). The original spike baseline was 22.1% recall / 63.0% precision on 77 annotated metrics.

**Document-type-aware config (implemented):**
```python
# Transcript processing — wider proximity, relaxed FP filter
config = PipelineConfig.for_transcript()

# Presentation processing — images enabled, relaxed FP filter, min_paragraph_chars=20
config = PipelineConfig.for_presentation()

# SEC filings — default behavior (unchanged)
config = PipelineConfig()
```

**Phase A (complete):** Value binding tuning, FP filter relaxation, period inference patterns, transcript converter, HuggingFace source, schema migration — all 12 ACs met. Achieved R=65.9% (target: ≥50%) on consolidated gold standard. See `ops/DEVELOPMENT_PLAN.md` for full AC list.

**Phase A+ (complete):** Precision hardening. Final scores (2026-03-02): R=75.8%, P=74.2%, F1=75.0% (91 annotations, 20 files). All targets met. Rules added: revenue_as_arr, forward_guidance, arpu_as_aov, percent_on_count_metric. ADBE FP cluster fixed (11→7 FPs).

**Phase B (complete):** Batch ingestion, HuggingFace E2E tested, schema migration 13, company upsert fixes, Web UI document-type filter.

**Phase C (complete, 72cd1c6 + 5b3b247):** Presentation support. New modules: `presentation_converter.py` (pdfplumber PDF→HTML), `sec_presentation_source.py` (EDGAR 8-K downloader), `scripts/ingest_presentations.py`. Section types TITLE_SLIDE/KEY_METRICS/FINANCIAL_OVERVIEW/GUIDANCE/APPENDIX added (migration 14). FP filter suppresses title/appendix slides and bare integers <1000. Period inference extended for slide title patterns. M5 (gold standard on real PDFs) deferred.

**Spike scripts:**
- `scripts/spike/collect_samples.py` — HuggingFace dataset downloader
- `scripts/spike/convert_transcript_to_html.py` — text-to-HTML converter
- `scripts/spike/run_poc.py` — pipeline POC runner

**Spike data:** `data/spike_samples/` (22 transcripts, 77 annotations), `data/spike_results/` (per-file results)

**Gold standard:** `data/transcript_gold_standard/` (per-filing `*_reviewed.csv`, 94 annotations, 16 files). Run `scripts/merge_transcript_annotations.py` to consolidate before benchmarking. Benchmark script: `scripts/validate_transcript_extraction.py`.

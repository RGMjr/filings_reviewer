# CLAUDE.md

## Project Overview

Python system for analyzing SEC S-1/F-1 filings to assess customer metric disclosures. Supports the Customer Metrics Accounting Standards Board (CMASB) initiative.

## Architecture

```
src/
├── infra/          # db.py, sec_client.py, http_client.py, logging_config.py, pool.py, validation.py, exceptions.py
├── universe/       # Filing discovery: classifiers.py, universe_builder.py
├── filing_fetcher/ # Document retrieval and caching
├── extraction/     # Metric extraction (V1 - production)
├── extraction_v2/  # Image/OCR pipeline (NOT in production — V2 was reverted; code present but inactive)
├── review/         # Human review: candidate_generator, pattern_analyzer
├── web/            # Flask app: routes/, templates/, static/
├── llm/            # OpenAI integration with SQLite-backed caching; includes vision_client.py and prompts.py
└── gold_standard/  # Validation: baseline.py, fresh_extractor.py
config/
└── metric_keywords.yaml  # Metric keyword patterns (authoritative source)
```

**Pipeline (V1):** UniverseBuilder → FilingFetcher → HTMLSegmenter → MetricClassifier → SegmentEnricher → ValueExtractor → QualityScorer → Database

## Key Commands

```bash
uv pip install -r requirements.txt # Install dependencies
pytest -v                          # Run all tests
pytest --cov=src --cov-report=html # Run with coverage
black src/ tests/                  # Format code
ruff check src/ tests/             # Lint
mypy src/review/ --strict          # Type checking
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

PostgreSQL. Key tables: `companies`, `filings`, `source_segments`, `metric_values`, `metric_definitions`, `review_candidates`, `review_decisions`. Schema files in `sql/` (00-09).

## Testing Standards

- **Coverage**: 75% minimum (enforced), currently 87%
- **Type safety**: `src/review/` passes `mypy --strict`
- **Structure**: `tests/unit/` (fast), `tests/integration/` (requires `TEST_DATABASE_URL`)
- **Before committing**: Run the full test suite (`pytest -x -q`). If fixing one failure breaks others, continue iterating until all pass in a single run before committing.

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
- `gold-standard.md` - Loaded when working with gold standard validation
- `testing.md` - Loaded when editing `tests/**`

## Available Commands

Use these slash commands for workflows:
- `/task-create [ID]` - Create a worker prompt for a task
- `/task-run [ID]` - Execute an existing worker prompt
- `/ralph [mode]` - Start Ralph Loop for autonomous execution
- `/metric-lifecycle` - Guide for adding/removing metrics
- `/commit` - Safe commit: runs ruff + pytest before committing
- `/merge-check` - Thorough merge readiness assessment (CI, migrations, imports, tests)
- `/ci-fix` - Autonomous CI fix loop: iterates ruff → mypy → pytest until all pass
- `/plan-execute` - Execute a multi-phase plan with parallel sub-agents per independent wave

## Implementation Rules

- Execute ONLY the steps specified. Do not expand scope, fix adjacent issues, or refactor beyond what was asked.
- When given a numbered plan, implement exactly those items. Do not add extra steps or address anything not listed.
- If you notice a related issue while working, call it out to the user rather than silently fixing it.

## Git Operations

- Before any force-push, force-merge, rebase, or reset --hard: show the exact command, show current branch/HEAD state, and wait for explicit user confirmation ("yes" — not a number, not ambiguous input).
- Never interpret ambiguous input as approval for destructive git operations.
- Never use `git add -A` or `git add .` without explicit user instruction. Stage specific files by name.

## Code Review / Audits

- When performing merge readiness assessments or code audits, do a thorough deep pass the first time. Do not produce superficial reports.
- Always check: CI status on the branch, migration file registration and ordering, import statements in changed files.
- Dropped imports and empty regex patterns from config moves are common failure modes — check for these explicitly.

## Shell Commands

- For multi-line shell commands, use heredocs or chain with `&&` / `;` on a single line.
- Do not use bare newlines between commands — they break in zsh.

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
**Status:** Phase A complete (12/12 ACs), Phase A+ complete (all targets met), Phase B complete, Phase C complete (M1-M4, M6; M5 deferred), Phase D complete
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

**Phase D (complete, 2026-03-03):** Monitoring, batch improvements, ingest_all wrapper, and M5 gold standard tooling. New scripts: `check_new_documents.py` (monitors HuggingFace + EDGAR for unprocessed documents), `ingest_all.py` (unified wrapper for both sources), `review_presentation_annotations.py` (terminal review UI), `merge_presentation_annotations.py` (60/40 split), `validate_presentation_extraction.py` (R/P/F1 benchmark). Circuit breaker (`--max-failures`) and `--resume` checkpointing added to both ingest scripts. See `docs/operations/BATCH_INGESTION.md` for full usage.

**Spike scripts:**
- `scripts/spike/collect_samples.py` — HuggingFace dataset downloader
- `scripts/spike/convert_transcript_to_html.py` — text-to-HTML converter
- `scripts/spike/run_poc.py` — pipeline POC runner

**Spike data:** `data/spike_samples/` (22 transcripts, 77 annotations), `data/spike_results/` (per-file results)

**Transcript gold standard:** `data/transcript_gold_standard/` (per-filing `*_reviewed.csv`, 91 annotations, 20 files). Run `scripts/merge_transcript_annotations.py` to consolidate before benchmarking. Benchmark script: `scripts/validate_transcript_extraction.py`.

**Presentation gold standard:** `data/presentation_gold_standard/` (per-filing `*_reviewed.csv`). Workflow: `preannotate_presentations.py` → `review_presentation_annotations.py` → `merge_presentation_annotations.py` → `validate_presentation_extraction.py`. File index at `data/presentation_gold_standard/_file_index.json`. Initial benchmark (2026-03-11): R=100.0%, P=36.8%, F1=53.8% (7 annotations, 5 files: CRM Q3+Q4 FY26, META Q4 2025, SNAP Q3+Q4 2025). SNAP precision is poor (29%) due to image-based investor letter generating spurious text candidates.

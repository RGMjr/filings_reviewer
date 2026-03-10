# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Image Pipeline Activation (2026-03-11)**:
- Stage 4 (Image Triage) validated end-to-end: Farfetch `g607688g54x53.jpg` classified as CHART, relevance=0.820
- Fixed `period_hint` on chart BoundValues: `chart_label` uses `point.x`, `chart_annotation` uses `annotation.period` — period confidence now ~0.85 (was 0.3)
- Wired `context.ocr_calls` / `context.vision_calls` counters in OCRExtractionStage
- Created `scripts/validate_image_pipeline.py` (Stage 4 triage diagnostic, no API key needed)
- Added 3 period_hint unit tests + `test_image_pipeline_replay.py` (replay with mocked VisionClient)
- Dual gold standard baselines: `v2_baseline.json` (text-only, CI), `v2_baseline_with_images.json` (image-enabled)
- Identified conftest.py load_dotenv() issue: OPENAI_API_KEY from .env enables Stage 5 in pytest sessions; fixed with explicit PipelineConfig in test
- Text-only: **P=95.0%, R=83.5%, F1=88.9%** | Image-enabled: **P=92.3%, R=83.5%, F1=87.7%**

**Cloud Independence Migration (2026-03-10)**:
- `html_content`/`txt_content` stored in PostgreSQL; extraction scripts read from DB with file fallback
- LLM cache: dual SQLite/Postgres backend via `LLM_CACHE_BACKEND=postgres`; SQL migrations 14+15; backfill script added

**Snowflake FN Fixes (2026-03-10)**:
- Recovered 5 Snowflake FNs: `cm_revenue_by_cohort` ×4 and `cm_new_customers_acquired` ×1
- Per-filing (text-only): Slack P=93.9%/R=96.9%, Samsara P=100%/R=100%, Farfetch P=92.3%/R=68.6%, Snowflake P=97.5%/R=84.8%

## Current Focus

- Address Farfetch date-parsing FP bug (value=30 from "June 30" month-day strings) as next quality task
- Assess PR #29 merge readiness; image pipeline activation is validated

## Test Status

- Unit tests: 1,128 passed (extraction_v2 suite); full suite ~3,310 passed
- V2 gold standard text-only: **P=95.0%, R=83.5%, F1=88.9%** — 12/12 pass
- V2 gold standard with images: **P=92.3%, R=83.5%, F1=87.7%** — 12/12 pass
- Farfetch chart recall still 68.6% with images — chart values not yet extracted (Stage 5 OCR for charts needs OPENAI_API_KEY in production)

## Key Learnings for Next Iteration

- `_check_vision_api_availability()` disables BOTH image triage AND chart extraction if no key; bypass by instantiating ImageTriageStage directly
- conftest.py `load_dotenv()` silently enables Stage 5 in pytest; always pass explicit PipelineConfig to gold standard validator
- Image-enabled baseline has lower precision (92.3% vs 95.0%) due to extra chart OCR FP candidates on table images
- Chart FNs in Farfetch (8 of 19) require labeled chart values — period_hint fix is ready, awaiting real Vision API smoke test

## Blockers or Warnings

- Farfetch chart FNs: image pipeline is validated but Farfetch recall won't improve until real GPT-4o chart extraction is confirmed (Step 2 deferred)
- Snowflake tables: colspan/grid-gap warnings — extraction works but may have binding gaps; accepted
- 6 transcript stub filings (IDs 1-6): always fail batch unless `html_storage_path IS NOT NULL` filter applied

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 65 lines - distill, don't dump.

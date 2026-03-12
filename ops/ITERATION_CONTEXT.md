# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Chart Extraction Pipeline Overhaul (2026-03-11)** — 6-phase refactor to increase image-derived metric recall:
- **Phase 0**: Added `enable_chart_interpolation`, `vision_provider`, `vision_model`, `image_triage_ambiguous_threshold` to `PipelineConfig`
- **Phase 1**: Extended `BoundValue` with `series_name`, `annotation_category`, `annotation_text`, `interpolated`; reworked `_bind_chart_candidate()` for series-aware binding (0.70x fallback + `requires_manual_capture=True` when no series name matches)
- **Phase 2**: Added `ImageExtractionMeta` dataclass; `ocr_extraction.py` now populates model/tokens/cost/latency/skip_reason per image
- **Phase 3**: Config-driven triage thresholds; `_get_nearby_text()` expanded (heading chain, 3 siblings, table captions, style dimensions)
- **Phase 4**: Two-pass chart extraction (`chart_prompts.py`); type-specific prompts; axis range validation; pie sum check
- **Phase 5**: `VisionProvider` protocol; `ClaudeVisionProvider`; `vision_factory.py`; `scripts/run_ab_comparison.py`
- **Keyword fix**: Added quantified-retention pattern to `cm_revenue_by_cohort` (`\d+%\s+of...\s+revenue...derived from existing/new customers`) — recovered Snowflake recall from 76.1% to 84.8%
- `cm_revenue_by_cohort` unconstrained from currency-only (accepts PERCENT for chart annotations like 44.4%)

**Farfetch Date FP Fix (2026-03-12)**: Added `_is_date_day_component()` pre-filter in `value_binding.py` — skips integers 1-31 that are immediately preceded by a month name in `_find_numbers_in_proximity()`. This prevents "June 30" day-of-month from binding as a metric value. 11 `TestIsDateDayComponent` tests + `test_find_numbers_year_not_fragmented` all pass; 3330 unit tests pass total.

**Image Pipeline Activation (2026-03-11)**:
- Dual gold standard baselines: `v2_baseline.json` (text-only, CI), `v2_baseline_with_images.json` (image-enabled)
- Text-only: **P=95.0%, R=83.5%, F1=88.9%** | Image-enabled: **P=92.3%, R=83.5%, F1=87.7%**

**Cloud Independence Migration (2026-03-10)**:
- `html_content`/`txt_content` stored in PostgreSQL; extraction scripts read from DB with file fallback
- LLM cache: dual SQLite/Postgres backend via `LLM_CACHE_BACKEND=postgres`; SQL migrations 14+15; backfill script added

## Current Focus

- Run real Vision API smoke test on Farfetch chart images to validate two-pass extraction
- Assess PR merge readiness for `v2-rewrite` branch

## Test Status

- Unit tests: ~3,330 passed (full suite)
- V2 gold standard text-only: **P=95.0%, R=83.5%, F1=88.9%** — 12/12 pass
- V2 gold standard with images: **P=92.3%, R=83.5%, F1=87.7%** — 12/12 pass
- Farfetch chart recall: 68.6% with image-enabled baseline (chart prompts ready; needs real API run)

## Key Learnings for Next Iteration

- Series-aware binding must fall back (0.70x + manual_capture) rather than reject — strict rejection caused Snowflake -8.7pp recall regression
- `cm_revenue_by_cohort` co-fires on percentage-quantified retention disclosures; pattern must require `\d+%` prefix to avoid Farfetch prose FPs
- Image-enabled baseline has lower precision (92.3% vs 95.0%) due to table-image OCR FP candidates — this is accepted for image-enabled runs
- Two-pass chart extraction budget: set `MAX_CHART_CALLS_PER_DOCUMENT = 20` (10 charts x 2 passes)

## Blockers or Warnings

- Farfetch chart FNs: two-pass prompts are implemented but need real GPT-4o run to confirm recall improvement
- Vision provider A/B comparison (`scripts/run_ab_comparison.py`) requires both `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`
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

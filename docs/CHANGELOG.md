# Changelog

Major milestones in reverse chronological order. Each entry summarizes a workstream or release; detailed task history is in `ops/ITERATION_CONTEXT.md` and completion summaries in `docs/analysis/`.

---

## [2026-03-11] — Chart Extraction Pipeline Overhaul + Image Pipeline Activation

- **Key Changes**: Six-phase refactor of chart extraction: series-aware binding (`BoundValue` extended with `series_name`/`annotation_category`), two-pass type-specific chart prompts, axis range validation, and pie-chart sum check. `VisionProvider` protocol added with `ClaudeVisionProvider` and `vision_factory.py` for A/B comparison between OpenAI and Anthropic vision models. Dual gold standard baselines introduced: `v2_baseline.json` (text-only, used in CI) and `v2_baseline_with_images.json` (image-enabled, manual gate).
- **Metrics Impact**: Text-only: P=95.0%, R=83.5%, F1=88.9%; Image-enabled: P=92.3%, R=83.5%, F1=87.7%. Snowflake recall recovered from 76.1% → 84.8% via `cm_revenue_by_cohort` quantified-retention pattern.

## [2026-03-10] — Cloud Independence Migration

- **Key Changes**: Filing HTML content (`html_content`, `txt_content`) now stored in PostgreSQL, eliminating filesystem dependency. LLM cache supports dual backend: SQLite (local dev) or Postgres (cloud) via `LLM_CACHE_BACKEND=postgres` env var. SQL migrations 14 (filings columns) and 15 (llm_cache table). Backfill script added. Step-by-step cloud deployment guide added (`docs/operations/v2-deployment-guide.md`).
- **Metrics Impact**: None (infrastructure only).

## [2026-02-28] — V2 Review UI + FP Hardening (v2.6)

- **Key Changes**: WP-21 complete — V2 review UI at full feature parity (`review_v2.py`, `api_v2.py`, `v2_filing_list.html`, `v2_review.html`, `v2_stats.html`). FP rules hardened: `_rule_tier_qualifier` (Snowflake tier FPs: 22→3) and `_rule_dollar_threshold_customer` (Slack ">$100K" FPs eliminated). SQL migration 12 drops V1 FK constraints on `source_segments`.
- **Metrics Impact**: Gold standard improved to P=92.8%, R=77.6%, F1=84.5% (all per-company gates passed).

## [2026-02-26] — V2 Production Promotion + Exception Architecture (v2.5)

- **Key Changes**: V2 pipeline promoted to `2.0.0-rc1`. Exception hierarchy added (`V2FatalError` / `V2TransientError`); all stages raise typed exceptions. `CANDIDATE_GENERATION` and `VALUE_BINDING` added to critical-stage set. Slack colspan/date-header parsing bugs fixed. V2 deployment guide added.
- **Metrics Impact**: No regression; baseline maintained.

## [2026-02-24] — Definition Extraction + Quality Scoring + Batch Extraction (v2.4)

- **Key Changes**: V2 Stage 9.5 definition extraction with ±5-window proximity scan and CMASB alignment scoring. `V2QualityScorer` writes all five rubric scores to `filing_metric_incidence`. Batch extraction script (`scripts/batch_v2_extraction.py`) with parallel workers, checkpointing, and graceful shutdown. SQL migration 11: `v2_metric_definitions` table.
- **Metrics Impact**: P=78.6%, R=79.2%, F1=78.9% at this stage (pre-FP hardening).

## [2026-02-17] — V2 Full Pipeline + Human Review (v2.3)

- **Key Changes**: V2 extraction pipeline complete across all 13 phases. V2 human review interface with fact-by-fact review and EvidencePack rendering. V2 false positive filter stage and percentage context detection. Gold standard validator for V2.
- **Metrics Impact**: Initial V2 gold standard baseline established.

## [2026-02-10] — V2 Pipeline Merge to Main

- **Key Changes**: 155-commit V2 pipeline merged from `v2-rewrite` branch. V2 becomes the sole extraction pipeline. V1 `src/extraction/` package retired and deleted. CI pipeline added (GitHub Actions, `WI-02`). Ledger-aware migration tracking (`WI-01`). V2 set as default UI.
- **Metrics Impact**: V2 replaces V1; full corpus re-extraction planned.

## [2025-12-29] — Goldmine Remediation Complete (v2.2)

- **Key Changes**: 16/18 goldmine remediation tasks complete; all targets exceeded. HRV-1 through HRV-5 human review validation complete. Performance optimizations (+33% throughput). Documentation reorganized; archive consolidated. Cohort chart image detection added at segment and filing level.
- **Metrics Impact**: V1 gold standard: 80% recall, 95% precision, 87% F1.

## [2025-12-14] — Human Review System Production Ready (v2.1)

- **Key Changes**: Full human-in-the-loop review system: `ReviewCandidate`, `ReviewDecision`, `LearnedPattern`, `CandidateFeatures` models. Review routes (D1: 94% coverage), API routes (D2: 97% coverage), pattern analyzer (E1: 97% coverage), rule applicator (E2: 100% coverage). V2 pipeline development begins in parallel.
- **Metrics Impact**: None (human review layer only).

## [2025-12-09] — V2.0 Complete Pipeline (v2.0)

- **Key Changes**: Complete extraction pipeline: LLM integration (GPT-4o-mini), quote verification, 77% test coverage. Universe builder, filing fetcher, OpenAI client, database schema all production-ready.
- **Metrics Impact**: Baseline V1 system operational.

## [2024-11] — V1.0 Initial Implementation

- **Key Changes**: Universe building, basic keyword-based extraction, PostgreSQL schema, SEC EDGAR integration.
- **Metrics Impact**: Initial proof of concept.

---

**Format**: Consolidate completion summaries from `docs/analysis/` into this file following the Quarterly Cleanup Checklist in `docs/DOCUMENTATION_MAINTENANCE.md`.

---
paths:
  - "src/extraction_v2/**"
  - "config/metric_keywords.yaml"
---

# V2 Extraction Pipeline

Ground-up redesign: 10x faster parsing (lxml), stable XPath locators, full table reconstruction, image/OCR integration, EvidencePack highlighting. All 13 phases complete.

## Pipeline Stages (`src/extraction_v2/stages/`)

ingestion → section_classification → table_reconstruction → image_triage → ocr_extraction → candidate_generation → value_binding → false_positive_filter → period_inference → fact_construction → definition_extraction → deduplication → validation → chart_fact_bridge (populates `v2_image_assets.detected_metrics` — **presence-only**, no per-value facts; see "Chart Metric Presence Config" below)

## Usage

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(
    enable_image_extraction=True,
    min_confidence_auto_accept=0.90,
)
pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)
# result.fact_count, result.facts, result.total_duration_ms
```

## Full-Page-Scan OCR (Path A + Path B)

Two orthogonal OCR entry points, both default-off, share a single
primitive: `VisionClient.analyze_image_for_text(image_bytes)` returning
`{"text", "contains_chart", "chart_hint"}` via `response_format={"type": "json_object"}`.
Cache key includes the prompt, so these calls don't collide with the
chart/table cached responses.

**Env-var wiring.** When `V2Pipeline()` is constructed without an explicit
`PipelineConfig`, `V2Pipeline._apply_env_feature_flags` lifts `FULL_PAGE_OCR_ENABLED=true`
and `IMAGE_KEYWORD_PRESCAN_ENABLED=true` into the default config. Explicit
configs always win over env (keeps GS validator and unit tests deterministic).
The ingestion UI → `onboarding_runner` → `process_filing(config=None)` path
relies on this; the backfill script passes an explicit config.

**Path A — full-page-scan filing** (`PipelineConfig.enable_full_page_ocr`).
`ImageTriageStage._detect_full_page_scan_filing` fires when `image_count >= 5`,
`images_per_page (= image_count / max(1, text_chars/2000)) >= 1.5`, and
`>=70%` of images are page-shaped (portrait aspect 0.7–0.85, width
900–1300, or dimensionless-but-large). When fired, page-shaped images
are reclassified as `ImageClassification.FULL_PAGE_SCAN` and
`context.full_page_scan_mode` is set to True. `OCRExtractionStage.process_full_page_scan`
text-OCRs each qualifying image, writes `v2_image_assets.ocr_text`, and
synthesizes a `Segment` (section_type=`PRESENTATION_SLIDE`,
source_type=`image_ocr`, source_img_id set) into `context.segments`.
If `contains_chart=True`, the existing `_process_chart_image` path runs
on the same image as a second pass (respects `MAX_CHART_CALLS_PER_DOCUMENT=10`).
Per-doc cap: `MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT=30`.

**Path B — image-level Tier-1 keyword pre-scan**
(`PipelineConfig.enable_image_keyword_prescan`). Skipped when
`context.full_page_scan_mode` is True. Runs at the top of
`OCRExtractionStage.process` on images where `classification == UNKNOWN`
and `0.2 <= relevance_score < 0.3`. Calls `analyze_image_for_text`; if
`TIER1_KEYWORDS_RE` matches the OCR text, promotes the image to
`CHART` (when `contains_chart=True`) or `TABLE_IMAGE`, synthesizes a
segment via `_synthesize_ocr_segment`, and the main loop then runs the
existing structured-extraction path on the promoted asset. No match →
OCR text stored on the asset for audit, no segment appended, image
stays UNKNOWN. Per-doc cap: `MAX_PRESCAN_CALLS_PER_DOCUMENT=10`.

**Segment provenance invariant.** Every segment synthesized by either
path carries `source_type='image_ocr'` and a non-null
`source_img_id` referencing the asset it was OCR'd from. Facts derived
from these segments flow through `candidate_generation → value_binding
→ fact_construction` unchanged — they classify as `source_type='text'`
at the fact level (no `v2_metric_facts.source_type` enum extension
needed). The image-derived provenance is captured on the segment only.
Rollback: `DELETE FROM v2_segments WHERE source_type='image_ocr'`
(cascades to facts via segment→fact FK). See
`docs/operations/full-page-ocr-runbook.md` for operator workflows and
verification SQL.

## Vision Model Selection

Per-site model knobs are documented in `docs/operations/vision-model-selection.md`.
Triage sites (`process_full_page_scan`, `_prescan_ambiguous_images`) default
to Gemini (`gemini-2.5-flash-lite`) regardless of `VISION_PROVIDER`. The
two-stage chart-read site defaults to Haiku-4.5 with a Sonnet fallback
that rescues low-confidence chart responses (PR 3). Cost is observed via
`PipelineResult.vision_spend_usd_by_site`; fallback rate via
`StageResult.metadata['chart_fallback_escalations']`.

## Image Asset Identity

`v2_image_assets` is unique on `(filing_id, filename)`; `img_id` is stable across re-extractions because `_persist_images_in_tx` upserts via `ON CONFLICT (filing_id, filename) DO UPDATE` and preserves the existing `img_id` on conflict. `persist_pipeline_result` uses the old→stable img_id map returned by `_persist_images_in_tx` to rewrite in-memory fact `source_locator.img_id` values before fact persistence, keeping metric-fact provenance consistent with the canonical DB row.

**`file_path` survives a NULL inbound (legacy-103, 2026-04-27):** the upsert clause is `file_path = COALESCE(EXCLUDED.file_path, v2_image_assets.file_path)`, so a force-reextract whose SEC fetch failed (transient outage, malformed URL) preserves the existing R2 storage key. Every other column still refreshes — only `file_path` is sticky against NULL.

**Synthetic accession URL construction (legacy-104, 2026-04-27):** filings ingested via `ingest_presentations.py` / `ingest_transcripts.py` carry synthetic `accession_number` values (`presentation:<cik>/<acc>/<file>`, `transcript:<...>`). EDGAR-URL construction sites (`SECClient.fetch_image`, `_get_image_cache_path`, `resolve_primary_document_url`, `get_filing_by_accession`, `_search_filings_array`, and `web/url_builders.build_image_cache_url`) all run `extract_sec_accession_token` from `src/infra/validation.py` to recover the embedded SEC token before building the URL. New URL-construction sites must do the same — `normalize_sec_accession` deliberately preserves the synthetic prefix for row-identity callers and is the wrong primitive for URLs.

**Detected-metrics invariant (chart-presence pivot, #86):** Every `v2_image_assets` row persists `detected_metrics` (JSONB, default `[]`) alongside the existing `chart_data`, `img_id`, and `file_path`. `ChartFactBridgeStage` populates `image.detected_metrics` from `ChartMetricClassifier.classify_all(...)`; `_persist_images_in_tx` round-trips the JSONB through the `ON CONFLICT (filing_id, filename) DO UPDATE` upsert so re-extraction overwrites cleanly. `scripts/check_image_referential_integrity.py` still runs in CI but is now trivially green (no chart facts → no `img_id` refs to validate); orphaned-asset and missing-on-disk checks still fire. The review UI's Detected-metrics card (`src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js`) surfaces each detected entry for reviewer accept / reject / correct / add via `POST /api/v2/image-metric-confirmations`. As of #86 + 2026-04-28, `ChartFactBridgeStage` scores both `chart_data` (chart path, via `ChartMetricClassifier`) and `ocr_table` (TABLE_IMAGE path, via `score_ocr_table` in `src/extraction_v2/chart/table_metric_classifier.py`). Both write into the same `v2_image_assets.detected_metrics` JSONB column — the review UI's `dataset.detectedMetrics` reader is source-agnostic.

## Reviewed-Filing Guard

`V2PersistenceAdapter._persist_facts_in_tx` (`src/extraction_v2/persistence.py`)
raises `ReviewedFilingError` (`src/extraction_v2/exceptions.py`) when a
filing has rows in `v2_review_decisions` and the caller did not pass
`force=True`. The guard exists because `v2_review_decisions.fact_id` has
`ON DELETE CASCADE` against `v2_metric_facts`; without the guard, re-running
extraction silently destroys reviewer work.

Public entry points that forward the flag:

- `persist_facts(facts, filing_id, *, force=False)`
- `persist_pipeline_result(result, filing_id, ..., *, force=False)`

CLI overrides:

- `scripts/run_v2_extraction.py --force-reextract`
- `scripts/batch_v2_extraction.py --force-reextract` (batch runner
  otherwise skips reviewed filings and reports them under `skipped` in the
  summary rather than failing)

When the override fires, the adapter emits a structured warning log:
`force-reextract purging reviewed filing: filing_id=X purged_decision_count=N distinct_reviewer_count=M`.
Purged decisions are **not archived** — recovery requires restoring from
a backup.

`_persist_images_in_tx` enforces a narrower variant (`ReviewedFilingError` with
`context="image classifications"`): it refuses re-extraction when an image with
an existing `v2_image_review_decisions` row would be re-classified from a
visible class (`chart` / `table_image` / `unknown`) into a hidden class
(`decorative` / `logo` / `signature`). The asset row is preserved by
`ON CONFLICT (filing_id, filename)`, so the decision survives — but the review
UI's `classification NOT IN ('decorative','logo','signature')` filter would
make it invisible. `force=True` proceeds and logs
`force-reextract hiding reviewed images: filing_id=X hidden_image_count=N filenames=[…]`.
Re-classifications within the visible set, or re-classifications of an
already-hidden image, are not blocked.

### Chart-only re-extraction (`chart_only=True`)

`persist_facts` and `persist_pipeline_result` accept `chart_only=True` to
scope the DELETE-then-INSERT to `source_type='chart'` only. Inbound
facts are filtered to chart facts; the DELETE is `WHERE filing_id=%s AND
source_type='chart'`; the reviewed-filing guard counts decisions on
chart facts only. Text facts and their reviewer decisions are untouched.

Use this mode to drain residual chart `v2_metric_facts` rows on filings
that already have accumulated reviewer decisions on text facts — the
full `force=True` escape is too destructive for that scenario. Under
the chart-presence pivot (#86), the chart pipeline no longer emits
new chart facts, so repeated `chart_only=True` runs are idempotent at
zero.

CLI: `scripts/batch_v2_extraction.py --chart-only` threads the flag
through the `BatchConfig` and `ProcessPoolExecutor` worker. Combine with
`--filing-ids-file PATH` to target a specific set of filings.

Applicability guard: `chart_only=True` is safe only when existing chart
facts (if any) have no reviewer decisions. The guard still raises
`ReviewedFilingError` if chart-fact decisions exist — pass `force=True`
alongside `chart_only=True` to explicitly accept that loss.

## Metric Priority Tiers

When improving keywords, FP rules, or value binding, prioritize **Tier 1** metrics. Tier definitions live in `config/metric_keywords.yaml` (`tier:` field). See CLAUDE.md for the full tier listing.

**Tier 1 measurement under the chart-presence pivot (#86, shipped 2026-04-23):**
Chart-native metrics are measured via **presence-F1** on `v2_image_assets.detected_metrics` (see `docs/GOLD_STANDARD_SPECIFICATION.md` and PR #150). Per-value value-F1 on chart rows is no longer meaningful — the pipeline does not emit per-value chart facts. Text/table-sourced facts continue to be measured via value-F1.

**Tier 1 measurement under the text-presence pivot (PR2, this PR):**
The Tier-1 regression gate now keys on **`tier1_presence_recall`** in `data/gold_standard/v2_baseline.json`, derived from `MetricPresenceStage` output (`PipelineResult.presences` — text + chart + definitions, aggregated). Fact-level Tier-1 R/P/F1, per-company drops, and chart `presence_f1` are computed and printed as `[informational]` but no longer set `has_regression`. See `docs/operations/text-pipeline-presence-pivot-plan.md` for the full pivot plan.

**Known chart-pipeline considerations (post-pivot):**
- **Chart OCR JSON quality** — `VisionClient.analyze_image()` passes `response_format={"type": "json_object"}` so gpt-4o returns valid JSON; `_parse_chart_json` has a truncation-repair fallback. Malformed `chart_data` now degrades the *presence signal* (classifier may miss a metric), not downstream per-value correctness.
- **Chart classifier scope** — `_scan_chart` in `src/extraction_v2/stages/candidate_generation.py` is gated off by `PipelineConfig.enable_chart_candidate_emission=False` (PR #147). Chart-sourced text candidates no longer enter the text pipeline; prior false positives (e.g., FTCH "44.4% New Consumers" annotation bleeding into `cm_new_customers_acquired`) are dissolved.
- **Chart-native metric gate in validator (resolved 2026-04-19, still in effect):** `src/gold_standard/v2_validator.py::_derive_chart_native_metrics` classifies a metric as chart-native when ≥80% of its ≥3 gold rows have `segment_type == 'chart'`. Under PR #150 these metrics flow through the presence-P/R path; text-derivable metrics still get value-level comparison.

**Classifier extension point:** `_COHORT_GATE_EXEMPT` and `_SUPPORTED_METRICS` in `src/extraction_v2/chart/metric_classifier.py` govern which metrics the classifier emits as presence signals. `_COHORT_GATE_EXEMPT` skips the cohort-structure check on series names; add a metric when its chart shape does not follow vintage-year or elapsed-period conventions but should still produce a presence record (e.g., tenure bucket labels for `cm_ltv_to_cac_ratio`).

**Tier 2 guidance:** Accept current performance. Simplify or relax FP rules for Tier 2 metrics if they create maintenance burden or interfere with Tier 1.

## Document-Type Configs

```python
PipelineConfig()                  # SEC filings (default)
PipelineConfig.for_transcript()   # Wider proximity, relaxed FP filter
PipelineConfig.for_presentation() # Images enabled, min_paragraph_chars=20
```

## Chart Metric Presence Config

`PipelineConfig` fields controlling the chart-presence emission path in `ChartFactBridgeStage` (post-#86 pivot):

```python
chart_image_min_confidence: float = 0.6     # Skip images below this vision confidence
chart_presence_min_score: float = 0.5       # Minimum ChartMetricClassifier.classify_all score
                                            # to emit a (metric_id, score) into
                                            # v2_image_assets.detected_metrics
enable_chart_candidate_emission: bool = False  # Gates `_scan_chart` in candidate_generation.
                                               # Leave False — re-enabling resurrects
                                               # chart-annotation FPs. Debug-only.
```

The retired per-value hallucination-guard fields (`chart_metric_classification_min_score`, `chart_metric_min_confidence`, `chart_fact_review_threshold`, `chart_axis_range_multiplier`) no longer exist — value-level guardrails are moot because no per-value facts are emitted.

## Key Files

- `pipeline.py` — orchestrator
- `models.py` — EvidencePack, Fact, PipelineResult dataclasses
- `persistence.py` — DB write layer
- `stages/false_positive_filter.py` — 34 FP rules (2,344 lines)
- `stages/value_binding.py` — number-to-metric binding (1,436 lines)
- `stages/period_inference.py` — date/period extraction (1,246 lines)

## Common Keyword/FP Regression Causes

| Change type | Common regression | Prevention |
|---|---|---|
| Adding broad primary keyword | FP spike | Add negative keywords or context gate |
| Removing negative keyword | FPs from financial-only mentions | Check existing FP filter coverage |
| FP filter too aggressive | Recall drops on valid mentions | Test with gold standard filings |
| FP filter too loose | Precision drops | Check per-company precision in GS |
| Number pattern change | Year fragments extracted as values | NUMBER_PATTERN must exclude 4-digit years |
| 2-digit year column headers (`20`, `21`, `22`, `23`) | FPs in fiscal-year table columns | `_rule_truncated_year` handles this; requires N±1 neighbor + `[CELL]`/`[ROW]` markers |
| Proximity window change | Binding wrong values to metrics | Keep window conservative (~250 chars) |

## Key FP Filter Notes

- `NUMBER_PATTERN` has no left-side word boundary — "M365" → extracts "365". Year-like values (4-digit numbers) must be excluded separately. 2-digit fiscal-year column headers (`20`–`35`) are caught by `_rule_truncated_year` via N±1 adjacency check; sub-spans of longer digit runs (e.g., `"20"` inside `"2023"`) are caught by the embedded-digit-run sub-rule.
- Growth rate percents ("up N% year-over-year") are only filtered by `_rule_growth_rate_percent` when a scale count also appears in the same segment. If the sentence has no absolute count, the percent is treated as the metric value.
- Transcript converter: speaker-pattern check must run **before** section detection. If reversed, Operator intro lines containing "question-and-answer" can trigger QA section detection and drop prepared-remarks speaker turns.

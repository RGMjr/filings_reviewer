---
paths:
  - "src/extraction_v2/**"
  - "config/metric_keywords.yaml"
---

# V2 Extraction Pipeline

Ground-up redesign: 10x faster parsing (lxml), stable XPath locators, full table reconstruction, image/OCR integration, EvidencePack highlighting. All 13 phases complete.

## Pipeline Stages (`src/extraction_v2/stages/`)

ingestion → section_classification → table_reconstruction → image_triage → ocr_extraction → candidate_generation → value_binding → false_positive_filter → period_inference → fact_construction → definition_extraction → deduplication → validation → chart_fact_bridge (optional, when enable_chart_fact_bridge=True)

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

## Metric Priority Tiers

When improving keywords, FP rules, or value binding, prioritize **Tier 1** metrics. Tier definitions live in `config/metric_keywords.yaml` (`tier:` field). See CLAUDE.md for the full tier listing.

**Current Tier 1 recall gaps (focus areas, measured 2026-04-17 post-chart-bridge-activation):**
- `cm_revenue_by_cohort` — F1=26.3% (up from 17% text-only). Chart bridge contributing; wider-proximity rejected (would add FPs without recovering TPs). Remaining FNs: chart OCR occasionally returns malformed JSON, dropping chart facts.
- `cm_balance_by_cohort` — F1=57.1% (up from 0% text-only). GS: 10 HOOD rows, all chart-embedded; chart bridge now bridging them correctly.
- `cm_gross_margin_by_cohort` — F1=0% pre-fix. GS: 9 FTCH rows, all chart images. Previously blocked by malformed vision JSON; fix applied 2026-04-17 (JSON mode + truncation-repair fallback, see "Chart OCR JSON failures" below). Re-measure GS to confirm lift.
- `cm_ltv_to_cac_ratio` — F1=20% (unchanged). Chart bridge's LTV tenure-bucket branch didn't lift this metric in GS — investigate classifier score threshold / `_COHORT_GATE_EXEMPT` coverage separately.

**Resolved (no longer gaps):**
- `cm_customer_retention_rate` — F1=100% (measured 2026-04-17); 1-row Chewy GS fully matched.

Text-pipeline Tier 1 recall work concluded 2026-04-16 (commits dd5c90a, 09a8f64); remaining gaps are chart-pipeline.

**Chart bridge activated in GS (2026-04-17):** Previously `pipeline.process(filing_id=0)` was called without `document_date`, so Phase A2 skipped chart-fact emission (correct, preserves idempotency). Fixed by adding `"filing_date": "YYYY-MM-DD"` to each `data/gold_standard/{Company}/metadata.json` and threading it through `v2_validator.py` at the `pipeline.process(..., document_date=...)` call site. `_load_filing_metadata` also gained a fuzzy-match fallback (mirroring `_find_filing_path`) because the CSV-name→directory-name sanitization otherwise returned `{}` for most companies.

**Known chart-pipeline issues surfaced by GS activation:**
- **Chart OCR JSON failures (fixed 2026-04-17):** `VisionClient.analyze_image()` now accepts `response_format` and `OCRExtractionStage` passes `{"type": "json_object"}` for both chart and table calls, forcing valid JSON from gpt-4o. `_parse_chart_json` adds a truncation-repair fallback that trims to the last balanced top-level brace (handles pre-JSON-mode cached responses and max_tokens cut-offs). `response_format` is part of the cache key so new mode doesn't collide with old entries.
- **Chart classifier mis-tag (fixed 2026-04-17):** FTCH "Marketplace Order Contribution Margin" annotations like `"44.4% New Consumers in 2017"` used to reach `cm_new_customers_acquired` via `_scan_chart` in `candidate_generation.py` (which runs all metric patterns over chart title+axes+annotations). Root cause: the annotation text literally says "new consumers". Fix: added exclusion `\b\d+(?:\.\d+)?%\s+(?:new|existing)\s+(?:consumers?|customers?)\b` to `cm_new_customers_acquired` — fires only on percent-prefixed segment labels, does not touch real prose like "acquired 500 new consumers, which was 44.4% of total" (verified in unit tests).
- **30% cross-source confirmation gate miscalibrated:** `CHART cross-source confirmation` at 0/20 in GS because chart-native cohort disclosures (e.g., HOOD `cm_balance_by_cohort`) have no text counterpart by design. The Phase 3 gate assumed text/chart redundancy; it needs to be metric-aware (text-derivable metrics enforce 30%; chart-native metrics bypass).

**Chart bridge extension point:** `_COHORT_GATE_EXEMPT` is a set of metric IDs in `src/extraction_v2/chart/metric_classifier.py` that skip the cohort-structure check on series names. Add a metric to this set when its chart data does not follow vintage-year or elapsed-period conventions but should still be bridged (e.g., tenure bucket labels for `cm_ltv_to_cac_ratio`).

**Tier 2 guidance:** Accept current performance. Simplify or relax FP rules for Tier 2 metrics if they create maintenance burden or interfere with Tier 1.

## Document-Type Configs

```python
PipelineConfig()                  # SEC filings (default)
PipelineConfig.for_transcript()   # Wider proximity, relaxed FP filter
PipelineConfig.for_presentation() # Images enabled, min_paragraph_chars=20
```

## Chart Fact Bridge Config

Three `PipelineConfig` fields control hallucination guards in `ChartFactBridgeStage` (Phase 3):

```python
chart_image_min_confidence: float = 0.6   # Skip images below this vision confidence
chart_fact_review_threshold: float = 0.80  # Flag facts for review below this confidence
chart_axis_range_multiplier: float = 10.0  # Reject outlier points >N× labeled max
```

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

---
paths:
  - "src/extraction_v2/**"
  - "config/metric_keywords.yaml"
---

# V2 Extraction Pipeline

Ground-up redesign: 10x faster parsing (lxml), stable XPath locators, full table reconstruction, image/OCR integration, EvidencePack highlighting. All 13 phases complete.

## Pipeline Stages (`src/extraction_v2/stages/`)

ingestion → candidate_generation → section_classification → value_binding → period_inference → deduplication → false_positive_filter → fact_construction → validation (+ ocr_extraction / image_triage for image-enabled runs) → chart_fact_bridge (after ocr_extraction, when enable_chart_fact_bridge=True)
# Note: stage ordering above differs from extraction-pipeline.md; reconcile in a future docs pass.

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

## Metric Priority Tiers

When improving keywords, FP rules, or value binding, prioritize **Tier 1** metrics. Tier definitions live in `config/metric_keywords.yaml` (`tier:` field). See CLAUDE.md for the full tier listing.

**Current Tier 1 recall gaps (focus areas):**
- `cm_revenue_by_cohort` — F1=31%, recall=23%. Wider-proximity was evaluated and rejected for this metric (FNs are table/chart-based; widening would add FPs without recovering TPs). Remaining gap is chart-pipeline. Phase 2 chart bridge in progress (2026-04-16).
- `cm_balance_by_cohort` — F1=0%. GS exists (10 Robinhood rows); all FNs are chart-embedded. Phase 1 chart bridge delivered (2026-04-16); recall gap expected to close.
- `cm_gross_margin_by_cohort` — F1=0%. GS exists (9 Farfetch rows); all FNs are chart images. Phase 1 chart bridge delivered (2026-04-16); recall gap expected to close.
- `cm_ltv_to_cac_ratio` — F1=50% (updated 2026-04-16). `specific_patterns` confidence boost + `_WIDER_PROXIMITY_METRICS` membership landed in commits `dd5c90a`/`09a8f64`. Phase 2 chart bridge in progress (2026-04-16).
- `cm_customer_retention_rate` — F1=50%. GS thinness (1 row Chewy); retention family dedup and FP rules are conservative; no text fix available per pipeline investigation.

Text-pipeline Tier 1 recall work concluded 2026-04-16 (commits dd5c90a, 09a8f64); remaining gaps are chart-pipeline.

**Chart bridge extension point:** `_COHORT_GATE_EXEMPT` is a set of metric IDs in `ChartFactBridgeStage` that skip the cohort-structure check on series names. Add a metric to this set when its chart data does not follow vintage-year or elapsed-period conventions but should still be bridged (e.g., tenure bucket labels for `cm_ltv_to_cac_ratio`).

**Tier 2 guidance:** Accept current performance. Simplify or relax FP rules for Tier 2 metrics if they create maintenance burden or interfere with Tier 1.

## Document-Type Configs

```python
PipelineConfig()                  # SEC filings (default)
PipelineConfig.for_transcript()   # Wider proximity, relaxed FP filter
PipelineConfig.for_presentation() # Images enabled, min_paragraph_chars=20
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
| Proximity window change | Binding wrong values to metrics | Keep window conservative (~250 chars) |

## Key FP Filter Notes

- `NUMBER_PATTERN` has no left-side word boundary — "M365" → extracts "365". Year-like values (4-digit numbers) must be excluded separately.
- Growth rate percents ("up N% year-over-year") are only filtered by `_rule_growth_rate_percent` when a scale count also appears in the same segment. If the sentence has no absolute count, the percent is treated as the metric value.
- Transcript converter: speaker-pattern check must run **before** section detection. If reversed, Operator intro lines containing "question-and-answer" can trigger QA section detection and drop prepared-remarks speaker turns.

---
id: 289
source: gh
slug: image-confidence-calibration-scope-b
title: Scope B — image confidence calibration and coverage expansion
status: resolved
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/chart/metric_classifier.py
  - src/extraction_v2/chart/table_metric_classifier.py
  - src/extraction_v2/stages/chart_fact_bridge.py
discovered: 2026-04-28
updated: 2026-05-04
gh_issue: 289
pr_refs:
  - 334
note: Soft-normalization and _SUPPORTED_METRICS expansion shipped via PR #334. Statistical calibration and LLM fusion accepted as deferred pending sufficient v2_image_metric_confirmations labels — file as new gh-N if/when label volume warrants. GH issue closed 2026-04-29.
---

### Problem

After Scope A (image-presence routing fix), `v2_image_assets.detected_metrics` is correctly populated for both chart-shaped and table-shaped images, but the underlying scoring formula has known calibration gaps: hardcoded `_MAX_POSSIBLE_RAW = 8.3` denominator that saturates above ~0.6 raw, narrow 5-metric `_SUPPORTED_METRICS` scope, uncalibrated weights, and no fusion with the Vision LLM's per-image confidence/predicted_metrics signal.

### Shipped (this PR)

- **Soft-normalization**: Replaced the magic constant `_MAX_POSSIBLE_RAW = 8.3` with a computed constant derived from explicit weight constants (`_W_SPECIFIC_TITLE`, `_W_PRIMARY_TITLE`, `_W_Y_AXIS`, `_W_AXIS_NEARBY`, `_W_ANNOTATIONS`). The value stays 8.3 — this is a maintainability fix so any future weight change automatically updates the denominator.
- **`_SUPPORTED_METRICS` expansion**: Both chart classifier (`metric_classifier.py`) and table classifier (`table_metric_classifier.py`) now score 9 metrics (up from 5), adding four Tier-1 chart-friendly metrics:
  - `cm_customer_retention_rate` — retention rate bar/line charts, exempt from cohort gate
  - `cm_net_revenue_retention` — NRR/NDR charts, exempt from cohort gate
  - `cm_customers_period_end_by_tenure` — elapsed-time tenure bucket charts, exempt from cohort gate (uses "Year 1"/"Year 2" axis labels, not calendar vintage years)
  - `cm_revenue_concentration` — top-N customer concentration charts, exempt from cohort gate
- **LLM-confidence fusion design** documented below (implementation deferred).

### LLM-confidence fusion design

`P(metric | image) = α * rule_score + (1 - α) * llm_confidence_signal`

Where:
- `rule_score` = `_score_metric` output (0–1), current implementation
- `llm_confidence_signal` = `image.confidence` (overall image quality) * per-metric probability from `predicted_metrics` when Vision LLM returns structured per-metric scores
- `α` = 0.7 (rule weight) proposed initially; tune against `v2_image_metric_confirmations` labels
- Fallback: pure `rule_score` when `image.predicted_metrics` is None/empty

### Remaining work

- **Statistical calibration** (Platt/isotonic): requires ~50+ accept/reject labels per metric class in `v2_image_metric_confirmations`. Re-run this when the corpus grows. Query to check readiness: `SELECT confirmed_metric_id, decision, COUNT(DISTINCT img_id) FROM v2_image_metric_confirmations GROUP BY 1, 2 ORDER BY 1, 2`.
- **LLM-confidence fusion implementation**: `predicted_metrics` from Vision LLM is not yet written to the image model in a structured per-metric probability form. Implement once the VisionClient returns per-metric scores.

---
id: 289
source: gh
slug: image-confidence-calibration-scope-b
title: Scope B — image confidence calibration and coverage expansion
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/chart/metric_classifier.py
  - src/extraction_v2/chart/table_metric_classifier.py
  - src/extraction_v2/stages/chart_fact_bridge.py
discovered: 2026-04-28
updated: 2026-04-28
gh_issue: 289
note: Scope-A routing fix landed; Scope B should calibrate weights against v2_image_metric_confirmations labels, drop the 8.3 denominator, expand _SUPPORTED_METRICS, and fuse the LLM confidence signal.
---

### Problem

After Scope A (image-presence routing fix), `v2_image_assets.detected_metrics` is correctly populated for both chart-shaped and table-shaped images, but the underlying scoring formula has known calibration gaps: hardcoded `_MAX_POSSIBLE_RAW = 8.3` denominator that saturates above ~0.6 raw, narrow 5-metric `_SUPPORTED_METRICS` scope, uncalibrated weights, and no fusion with the Vision LLM's per-image confidence/predicted_metrics signal.

### Next Steps

- Calibrate weights against `v2_image_metric_confirmations` labels (Platt or isotonic).
- Replace the `8.3` denominator with a soft normalization derived from the weight table.
- Expand `_SUPPORTED_METRICS` to additional Tier-1 chart/table image-friendly metrics.
- Design fusion of rule-based score + LLM confidence + predicted_metrics into a calibrated `P(metric | image)`.

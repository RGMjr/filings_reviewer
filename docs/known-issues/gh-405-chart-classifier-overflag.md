---
id: 405
source: gh
slug: chart-classifier-overflag
title: Investigate over-flagging by chart classifier (image_features model coefficient signal)
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 405
note: investigation complete — relevance model absorbs the signal correctly; see docs/analysis/gh-405-chart-classifier-overflag-audit.md
---

### Problem

The retrained image relevance model (logistic regression, AUC 0.829, 1499 labels) has its strongest negative coefficient on `is_chart_classification: -2.178`. Counterintuitive: when the upstream chart classifier labels something as a chart, the per-reviewer label is *less* likely to be relevant. Useful signal for the relevance model, but it implies the chart classifier itself over-flags — most "chart" labeled images are noise after human review. The rule-based "tier_1_cohort" baseline reaching only Precision 0.175 supports the same hypothesis.

### Next Steps

- Audit the chart-classification threshold / feature gates in `src/extraction_v2/stages/image_classify.py` (or wherever `v2_image_assets.classification` is set).
- Cross-check per-reviewer accept/reject rates per `classification` value via `v2_image_metric_confirmations` to quantify the overflag rate.
- Consider tightening the chart-label threshold or adding a secondary feature gate (minimum dimensions, axis-text OCR signals).

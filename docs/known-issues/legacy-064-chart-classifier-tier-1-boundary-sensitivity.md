---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 64
severity: n/a
slug: chart-classifier-tier-1-boundary-sensitivity
source: legacy
status: archived
title: Chart Classifier Tier 1 Boundary Sensitivity
touches: []
updated: '2026-04-22'
---

`ChartMetricClassifier.classify` scored the HOOD "Cumulative Net Deposits by Cohort" fixture at 0.6024 — only 0.0024 above the 0.6 classification gate — creating a silent-regression risk if any future keyword or weight change narrowed the margin.

Resolved by adding `tests/extraction_v2/chart/test_chart_classifier_margin.py`: a parametrized characterization test that measures empirical scores for three Tier 1 chart fixtures (HOOD `cm_balance_by_cohort` at 0.6024, Farfetch `cm_gross_margin_by_cohort` at 1.0000, FTCH empty-axes `cm_gross_margin_by_cohort` at 0.6627), locks in score floors (measured score − 0.005), and also asserts the 0.60 gate. Any future re-weighting that narrows the margin fails loudly. Classifier itself is untouched.

Cross-references: Issue #54 — `chart_metric_min_confidence` knob; `src/extraction_v2/chart/metric_classifier.py`.

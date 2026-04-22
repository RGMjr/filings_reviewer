---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 20
severity: n/a
slug: cm-gross-margin-by-cohort-still-0-on-farfetch-despite-chart
source: legacy
status: archived
title: '`cm_gross_margin_by_cohort` Still 0% on Farfetch Despite Chart Pipeline Active'
touches: []
updated: '2026-04-22'
---

Four targeted changes in `src/extraction_v2/chart/`: `_cohort_gate` accepts ≥2 distinct years in `points[].x` + customer-type series names; `_metric_gate` fallback for empty `y_axis_label`; `_score_metric` nearby_text title fallback + structural bonus; `cohort_parser._parse_customer_type_regime` new regime. `cm_gross_margin_by_cohort` Farfetch 0%→100% F1 (9/9 rows); Tier 1 F1 +5.4pp overall. 7 regression tests added. See git log (2026-04-18).

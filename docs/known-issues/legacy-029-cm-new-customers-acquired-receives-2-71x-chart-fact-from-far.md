---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 29
severity: n/a
slug: cm-new-customers-acquired-receives-2-71x-chart-fact-from-far
source: legacy
status: archived
title: '`cm_new_customers_acquired` Receives `2.71x` Chart Fact From Farfetch LTV/CAC
  Chart'
touches: []
updated: '2026-04-22'
---

`_rule_ratio_suffix_on_count_metric` added to `src/extraction_v2/stages/false_positive_filter.py`; rejects `N.NNx`/`N.NN×` raw values on count/currency/rate/time metrics. 6 unit tests. Farfetch GS confirms the `2.71x` FP eliminated. See git log (2026-04-19).

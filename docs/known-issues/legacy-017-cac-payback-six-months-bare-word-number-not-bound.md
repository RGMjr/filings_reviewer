---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 17
severity: n/a
slug: cac-payback-six-months-bare-word-number-not-bound
source: legacy
status: archived
title: CAC Payback "Six Months" — Bare Word-Number Not Bound
touches: []
updated: '2026-04-22'
---

`WORD_NUMBER_TIME_PATTERN` regex added to `value_binding.py`, gated to `TIME_UNIT_VALUED_METRICS = {"cm_cac_payback_period"}`; `_V1_SPELLED_OUT_OVERRIDE_METRICS` bypass added to `false_positive_filter.py`. `cm_cac_payback_period` 0%→100% F1 on Farfetch. 6 unit tests added. See git log (2026-04-18).

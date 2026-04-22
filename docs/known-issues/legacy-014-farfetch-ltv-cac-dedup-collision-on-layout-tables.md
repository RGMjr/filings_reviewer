---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 14
severity: n/a
slug: farfetch-ltv-cac-dedup-collision-on-layout-tables
source: legacy
status: archived
title: Farfetch LTV/CAC Dedup Collision on Layout Tables
touches: []
updated: '2026-04-22'
---

Respectively-parser priority introduced in `value_binding.py::_bind_prose_cell`; `cohort_hint` field added to `BoundValue`; defensive 80-char prose guard in `_extract_cohort_def`. `cm_ltv_to_cac_ratio` R 33%→100%; `cm_ltv_to_cac_ratio_by_cohort` R 17%→50% (text FNs); Farfetch F1 +10.3pp. 6 regression tests added. See git log (2026-04-18).

---
autonomy: n/a
discovered: '2026-04-18'
estimated: M
id: 16
note: 'Dissolved by presence-first pivot (2026-04-24). Issue is purely value-level
  precision (table-scale inference, period attribution); facts are advisory under
  the pivot and the Tier 1 gate no longer counts these FPs. See
  docs/operations/text-pipeline-presence-pivot-plan.md.'
severity: low
slug: farfetch-precision-drag-table-scale-period-attribution
source: legacy
status: archived
title: Farfetch Precision Drag — Table-Scale + Period Attribution
touches: []
updated: '2026-04-24'
---

### Problem

Two Tier 2 Farfetch metrics show high recall but low precision due to table-scale inference producing near-match FPs:

- `cm_active_customers_total`: P=29%, R=100%, 5 FPs. Examples:
  - raw `935.8` → 935,800 (table "in thousands" applied); gold=796,297 in same period → BOTH_MISMATCH
  - raw `1,118.0` → 1,118,000 in 2018-H1; gold=796,297 in 2017-H1 → period + value mismatch
- `cm_purchase_transactions_overall`: P=25%, R=100%, 4 FPs. Same pattern (raw `800.5` → 800,500, etc.).

### Root Cause

For each period (e.g., 2015, 2016, 2017 + H1), the system extracts ONE correct value and several near-match values from adjacent periods with slightly different scales. These produce period-mismatch or value-mismatch FPs rather than clean TPs.

### Next Steps

- Investigate whether period-attribution logic can be tightened to prefer the nearest-period match when multiple extracted values share a metric.
- Consider dedup-collapsing same-metric near-matches that share source-locator ancestors.
- Low priority; doesn't affect recall or Tier 1.

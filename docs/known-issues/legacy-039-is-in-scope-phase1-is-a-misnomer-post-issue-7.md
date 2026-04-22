---
autonomy: skip
discovered: '2026-04-19'
estimated: M
id: 39
note: Column rename; needs migration ordering decision
severity: low
slug: is-in-scope-phase1-is-a-misnomer-post-issue-7
source: legacy
status: open
title: '`is_in_scope_phase1` Is a Misnomer Post-Issue-#7'
touches: []
updated: '2026-04-19'
---

### Problem

`filings.is_in_scope_phase1` suggests "this filing is in the active
universe." Its actual semantic is stricter: "this is an S-1/F-1 filing
from a first-time non-SPAC non-investment-vehicle non-resource-extraction
issuer" (classifiers.py:832-834). With 10-K support (Issue #7) landed,
10-K rows correctly have `is_in_scope_phase1=FALSE` — but that reads as
"out of scope" to anyone browsing `filings`. The column and query-time
filter are now confusing.

### Suggested Fix

Two options:

1. **Rename column** → `is_phase1_ipo_candidate` (scoped to S-1/F-1 by
   design). Migration + updates to `filings` upserts, discovery SQL in
   `scripts/onboard_tickers.py::_build_discovery_sql`, gold-standard
   validator queries, any `WHERE is_in_scope_phase1 = ...` usage.
2. **Add a form-aware companion column** `is_customer_metric_candidate`
   that's true for S-1/F-1 FTI _and_ true for 10-K/10-K/A that pass basic
   filters (non-SPAC, non-investment-vehicle, non-resource-extraction).
   Leave `is_in_scope_phase1` as-is for historical callers.

Option 2 is less disruptive but adds DB surface area. Option 1 is
conceptually cleaner but requires a coordinated migration + code sweep.

Bundle with Issue #38 if tackled — both are column-name clarifications in
the same schema area.

### Cross-References

- `src/universe/classifiers.py:832-834` — `is_in_scope_phase1` definition
- `scripts/onboard_tickers.py::_build_discovery_sql` — already has a
  workaround (conditionally omits the Phase-1 filter for non-S-1/F-1
  form types)
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
  section documents the current confusing behavior
- Issue #7 — introduced 10-K support that makes the misnomer visible

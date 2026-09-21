---
autonomy: skip
discovered: '2026-04-19'
estimated: —
id: 40
note: Stakeholder confirmed restatement-supersedes-original; 10-K/A demotes same-fiscal-year 10-K via period_end_date partition
severity: low
slug: 10-k-a-supersession-semantics-undefined
source: legacy
status: archived
title: 10-K/A Supersession Semantics Undefined
touches: []
updated: '2026-04-28'
---

### Problem

`UniverseBuilder` after-loop step `self.db.mark_superseded_filings()`
(universe_builder.py:107) demotes earlier S-1/S-1/A/F-1/F-1/A filings per
CIK — "only the latest amendment in scope." For 10-K/A (restatements),
the method is scoped to S-1/F-1 only; 10-K and 10-K/A rows are preserved
as separate in-scope entries.

Two defensible interpretations:

- **"Restatement replaces original":** 10-K/A is the corrected version —
  the original is misleading and should be marked superseded. Matches
  S-1/A semantics.
- **"Both are distinct fiscal-year events":** each row represents a
  point-in-time filing with different disclosures; analytics may want to
  compare pre- vs post-restatement. Current behavior.

Current behavior is option 2 (both survive). No one has validated this is
the intended operator workflow; no 10-Ks are in prod today (Issue #7 just
shipped the capability).

### Suggested Fix

Before the first operator bulk-onboards 10-Ks:

1. Decide which semantic matches the analytic use case (ask CMASB
   stakeholders).
2. If "restatement replaces": extend `mark_superseded_filings` to include
   10-K/A pairs, add a test, document in the runbook.
3. If "both distinct": document the decision in
   `docs/operations/TICKER_ONBOARDING.md` under "10-K onboarding semantics"
   so reviewers / analysts know what to expect.

Lightweight either way — <30 LOC + tests + doc line.

### Cross-References

- `src/universe/universe_builder.py:107` — `mark_superseded_filings` call
- `src/infra/db.py::mark_superseded_filings` — form-type scope
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
- Issue #7 — landed 10-K support without resolving this

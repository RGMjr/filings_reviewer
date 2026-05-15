---
id: 633
source: gh
slug: phase2-cost-per-filing-estimate-stale
title: Phase-2 _COST_PER_FILING_USD planning estimate is ~15× too low on real corpus
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-15
updated: 2026-05-15
gh_issue: 633
note: Bump _COST_PER_FILING_USD from $0.25 to ~$4 based on 2026-05-14 v2 run ($194.79/52 filings = $3.75/filing); current value misleads pre-flight cost estimate.
---

### Problem

`_COST_PER_FILING_USD = 0.25` in `scripts/run_phase2_quantitative_eval.py` was a pre-live-run guess. The 2026-05-14 v2 run (52 filings, $194.79) establishes the real per-filing cost at ~$3.75, ~15× the constant. The pre-flight cost estimate ("Estimated cost: $X for N filings") therefore materially under-reports, and operators passing `--i-accept-cost` based on it get a much larger bill than expected. The cost-budget guard works correctly; its input is stale.

### Next Steps

- Update `_COST_PER_FILING_USD` to ~$4 (or the empirically-derived mean) with a comment citing the 2026-05-14 v2 run.
- Verify the in-loop ETA formula still produces sensible numbers (uses the same constant).
- Consider whether `--cost-budget` default of $25 should also rise.

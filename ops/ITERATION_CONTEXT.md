# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- V2 precision: 73% → 74.3% via Unit.OTHER filter for currency metrics in text_proximity (b7e0aad)
- Defensive column-type filter in _bind_row_values (44a8987) — zero gold standard impact but guards future
- Diagnosed Farfetch FPs: 6/8 are text_proximity, only 2 are table_stub
- Min-value threshold (< 100) for count metrics tested and REJECTED — causes -10pp recall

## Current Focus

- V2 gold standard precision/recall optimization (ongoing)

## Test Status

- 4,396 unit tests passed, 81% coverage
- V2 gold standard: P=74.3%, R=53.1%, F1=61.9% (overall, 4 companies)
- V1 gold standard: P=89.4%, R=63.2%, F1=74.1% (unchanged)
- Pre-commit scoped to unit tests only

## Key Learnings for Next Iteration

- Unit.OTHER rejection must be text_proximity-specific (table bindings need bare numbers)
- Min-value thresholds for count metrics destroy recall (Snowflake has legitimate small counts)
- Farfetch FPs are mostly text_proximity, not table bindings — column-type filters have limited impact
- Pre-commit hook runs V1 gold standard, not V2 — V2 needs separate validation

## Blockers or Warnings

- None currently

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. List files modified in "Files Changed"
6. Note any blockers for next iteration

Keep this file under 50 lines - distill, don't dump.

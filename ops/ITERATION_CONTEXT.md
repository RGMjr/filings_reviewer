# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

- V2 F1: 61.9% → 69.6% (+7.7pp) via 3 fixes targeting Farfetch recall
- Fix 1: normalize_value() double-scale bug — scaled_value already incorporates scale_unit
- Fix 2: Ratio metrics (LTV/CAC, repeat purchase) now accept Unit.OTHER (bare decimals)
- Fix 3: "except as otherwise noted" table scale — skip scaling for $-prefixed/(actual) values
- Farfetch: F1 42.3% → 66.7% (+24.4pp), Snowflake: F1 61.6% → 74.7% (+13.1pp)

## Current Focus

- V2 gold standard optimization — remaining FNs are mostly OCR-dependent (chart images)

## Test Status

- 4,405 unit tests passed (17 skipped), 87% coverage
- V2 gold standard: P=81.9%, R=60.6%, F1=69.6% (overall, 4 companies)
- V1 gold standard: P=89.4%, R=63.2%, F1=74.1% (unchanged)
- Pre-commit scoped to unit tests only

## Key Learnings for Next Iteration

- Gold standard CSV scaled_value column already incorporates scale_unit — don't re-apply
- Ratio metrics (LTV/CAC) naturally appear as bare decimals — need Unit.OTHER, unlike true percents
- "except as otherwise noted" is a common SEC filing pattern — $ symbol = actual value
- Farfetch remaining FNs: 9 chart-only (gross_margin_by_cohort, ltv_to_cac_ratio_by_cohort)

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

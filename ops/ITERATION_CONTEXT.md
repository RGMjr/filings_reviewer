# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-09 (partial, 2026-02-20)**: Farfetch CSV cleanup (4 empty-metric rows removed) + scale exemption for `(actual)` stub rows (commits 628ca47, 01e3838)
- Farfetch FN: 24 → 22 (2 no_candidate FNs resolved via CSV cleanup)
- Scale fix prevents ×1000 inflation on AOV rows labelled `(actual)` — correct, but AOV FNs still `wrong_period`

### Farfetch V2 scores (no image extraction): TP=10, FP=2, FN=22 — P=83.3%, R=31.2%, F1=45.5%

Remaining Farfetch FN breakdown:
- **9 FNs (LTV/CAC)**: fp_filtered — "31" (from "December 31") bound instead of "1.42, 1.53..." — multi-value not supported
- **8 FNs (charts)**: no_value_binding — requires Vision API
- **5 FNs (AOV)**: wrong_period — values extracted at correct scale but period inference assigns wrong dates

## Current Focus

- WP-09 remaining: LTV/CAC multi-value binding (9 FNs) — significant feature; needs new design
- AOV wrong_period (5 FNs) — blocked by WP-08 (period inference for non-calendar FY)
- Slack table binding fix: complex colspan headers (new WP needed)
- Baseline refresh: v2_baseline.json needs update after all WPs complete

## Test Status

- 4,765 tests total; 87% coverage (as of 2026-02-10)
- V2 gold standard stored baseline: P=81.9%, R=60.6%, F1=69.6% (as of 2026-02-18)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1% (pre-commit hook passes)

## Key Learnings for Next Iteration

- Farfetch LTV/CAC: "31" (nearest number) bound instead of "1.42, 1.53"; multi-value comma lists unsupported
- AOV wrong_period: values ARE extracted at correct scale; period mismatch is the gating issue (needs WP-08)
- `_is_scale_exception` now fires on `(actual)` stub unconditionally; currency-symbol check still gated
- FN diagnostic `wrong_period` with `closest != None` means value is found but period doesn't overlap
- V2 baseline (v2_baseline.json) is stale — set Feb-18, pre-WP-02; comparison against it is misleading

## Blockers or Warnings

- Stored v2_baseline.json needs refresh after all WPs complete
- Farfetch chart FNs (8) require Vision API; not addressable in current test environment

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.

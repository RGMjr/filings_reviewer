# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-12 (refactor)**: Extract number_parsing module, FP rule registry, period pattern lists (commits 85e0c87, b3b116c)
**WP-06 (investigation)**: Farfetch FN root cause analysis complete (2026-02-19); see ops/ANALYSIS_RESULTS.md

### Farfetch V2 scores (no image extraction): TP=10, FP=2, FN=24 — P=83.3%, R=29.4%, F1=43.5%

Farfetch FN root causes:
- **9 FNs (LTV/CAC)**: Value binding picks "31" from "December 31" (closer to keyword) instead of "1.42, 1.53..." — multi-value comma-separated binding not supported
- **8 FNs (charts)**: cm_gross_margin_by_cohort (6), cm_revenue_by_cohort (1), cm_cac_payback_period (1) — requires Vision API
- **5 FNs (AOV)**: Values bound at bc=0.70 but dedup or scale-table contamination (table×1000) prevents match
- **2 FNs**: Empty metric_id rows in CSV

## Current Focus

- WP-09: Fix Farfetch recall — 3 addressable issues: (1) multi-value extraction, (2) AOV dedup explosion, (3) scale table contamination
- Slack table binding fix: complex colspan headers prevent table reconstruction (new WP needed)
- Baseline refresh: v2_baseline.json needs update after all WPs complete

## Test Status

- 4,765 tests total; 87% coverage (as of 2026-02-10)
- V2 gold standard stored baseline: P=81.9%, R=60.6%, F1=69.6% (as of 2026-02-18)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1% (pre-commit hook passes)

## Key Learnings for Next Iteration

- Farfetch LTV/CAC: value binding picks nearest number; "December 31" beats "1.42" in proximity scoring
- AOV mass-duplication: table `c4f2ffc3` generates hundreds of bindings (candidates × table cells)
- Scale contamination: table `3950ef78` has "(in thousands)" — AOV values ×1000 wrong
- The `fp_filtered` diagnostic can be misleading: a DIFFERENT value (not the target) was bound and removed

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

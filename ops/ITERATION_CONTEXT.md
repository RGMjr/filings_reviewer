# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-09 LTV/CAC respectively-pattern binding (2026-02-23)**: Integrated V1 `respectively_parser` into V2 value binding + period inference
- `_bind_respectively_pattern()` method added to ValueBindingStage; fallback fires when prose cell yields no results
- Strategy 0 in PeriodInferenceStage uses `period_hint` from respectively parser before all other strategies
- `BoundValue.period_hint` new field carries pre-parsed period string ("2015"/"2016"/"2017")
- Farfetch TP: 10 → 16, FN: 22 → 16; R: 31.2% → 50.0%; P=88.9%, F1=64.0%
- Real mechanism: Strategy 1 (column binding) already found the values; the fix correctly assigns distinct annual periods via `period_hint` instead of all landing on 2015-12-31
- 0 respectively-pattern facts in Snowflake or Slack — no regressions
- 7 new unit tests added (4 value_binding, 3 period_inference); full suite 4352 passed

### Farfetch V2 scores (no image extraction): TP=16, FP=2, FN=16 — P=88.9%, R=50.0%, F1=64.0%

Remaining Farfetch FN breakdown:
- **8 FNs (charts)**: no_value_binding — requires Vision API
- **5 FNs (AOV)**: wrong_period — values extracted at correct scale but period inference assigns wrong dates
- **3 FNs (LTV/CAC)**: remaining after respectively fix (gold standard period overlap edge cases)

## Current Focus

- AOV wrong_period (5 FNs) — blocked by WP-08 (period inference for non-calendar FY)
- Slack table binding fix: complex colspan headers (new WP needed)
- Baseline refresh: v2_baseline.json needs update after all WPs complete

## Test Status

- 4,352 unit tests; 82% coverage (as of 2026-02-23)
- V2 gold standard stored baseline: P=81.9%, R=60.6%, F1=69.6% (as of 2026-02-18, stale — pipeline_version="v1")
- V1 baseline: P=89.4%, R=63.2%, F1=74.1% (pre-commit hook passes)

## Key Learnings for Next Iteration

- Farfetch LTV/CAC: respectively parser fix works via period_hint, not via larger proximity window
- AOV wrong_period: values ARE extracted at correct scale; period mismatch is the gating issue (needs WP-08)
- `_is_scale_exception` fires on `(actual)` stub unconditionally; currency-symbol check still gated
- FN diagnostic `wrong_period` with `closest != None` means value is found but period doesn't overlap
- V2 baseline (v2_baseline.json) is stale — set Feb-18, pre-WP-02; comparison against it is misleading
- `_try_parse_plain_year()` handles bare "2017" but isn't in `_try_parse_all_patterns` pattern list

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

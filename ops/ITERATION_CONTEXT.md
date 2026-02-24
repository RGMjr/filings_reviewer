# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-10–14 Production readiness (2026-02-24)**: Table resilience, batch hardening, review_status preservation, stale metadata fix
- WP-10: Table reconstruction `success` only False when zero tables processed (errors → warnings)
- WP-11: Batch executor created once outside loop; `--max-consecutive-failures` flag (default 10); exit 1 when failure rate > 50%
- WP-12: `review_status` removed from `DO UPDATE SET` — reviewer decisions survive re-extraction
- WP-13: JSON summary written to `logs/batch_v2_summary_{timestamp}.json` at batch completion
- WP-14: `v2_baseline.json` `pipeline_version` fixed to `"v2"`; iteration context updated

**WI-04/05 async audit + pagination (merged ea365a4)**
**WI-01–03 (merged earlier)**

## Current Focus

- AOV wrong_period (5 FNs) — WP-08 in-flight
- Slack table binding fix: complex colspan headers (WP in-flight)

## Test Status

- 4,765 unit tests; 87% coverage (as of 2026-02-24)
- V2 gold standard baseline: P=78.6%, R=79.2%, F1=78.9% (2026-02-24, pipeline_version="v2")
- V1 baseline: P=89.4%, R=63.2%, F1=74.1%

## Key Learnings for Next Iteration

- Farfetch LTV/CAC: respectively parser fix works via period_hint, not larger proximity window
- AOV wrong_period: values ARE extracted at correct scale; period mismatch is the gating issue
- `_is_scale_exception` fires on `(actual)` stub unconditionally; currency-symbol check still gated
- FN diagnostic `wrong_period` with `closest != None` means value found but period doesn't overlap
- V2 FP pattern: 22/27 FPs are value_mismatch on cm_customers_period_end (Snowflake per-tier)

## Blockers or Warnings

- Farfetch chart FNs (8) require Vision API; not addressable in current test environment
- AOV/Slack WPs in-flight on v2-rewrite branch

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 60 lines - distill, don't dump.

# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-15–22.5 Production readiness Phase 1–3 (2026-02-28)**:
- WP-15: `_rule_tier_qualifier` in `false_positive_filter.py` — Snowflake tier FPs 22→3
- WP-16: Closed (AOV period FNs already fixed by 44a1e81 off-by-one fix)
- WP-17: `_rule_dollar_threshold_customer` — Slack "Paid Customers >$100K" FPs eliminated; Slack F1 77.1%→92.3%
- Gold standard validated: **P=92.8%, R=77.6%, F1=84.5%** (all per-company gates passed)
- WP-18+19: Batch script hardened (private API removed, production guard, datetime.utcnow→timezone.utc, .env.template updated)
- WP-20: `src/extraction_v2/logging_config.py` — JSON structured logging, optional Sentry hook
- WP-22: `scripts/compare_v1_v2_results.py` — V1/V2 DB-based comparison script
- WP-22.5: Consumer audit complete (see Blockers)

**WP-10–14 (2026-02-24)**: Table resilience, batch hardening, review_status preservation

## Current Focus

- WP-21: Review UI V2 verification (feature parity check for v2 review routes/templates)
- WP-23: Batch V2 extraction on remaining 8 filings (depends on WP-15–18 complete ✓)
- Migration 12: `sql/12_drop_v1_fk_constraints.sql` — drop FK deps on source_segments before cutover

## Test Status

- Unit tests: 1,110 extraction_v2; full suite ~4,765 (coverage 87%)
- V2 gold standard: P=92.8%, R=77.6%, F1=84.5% (2026-02-28, post-WP-15+17)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1%

## Key Learnings for Next Iteration

- `_rule_dollar_threshold_customer`: check source_text for ">$100,000" proximity — simpler than colspan fix
- AOV wrong_period FNs: were already fixed in 44a1e81 (period start off-by-one). Always re-check before investigating.
- `source_segments` has FK deps in migrations 07/08/09 — cannot drop without migration 12 first
- `metric_values` has NO FK dependents — safe to drop/rename independently
- WP-22 comparison script uses `resolve_to_canonical()` from `src/extraction/keyword_config.py` (not metric_registry)

## Blockers or Warnings

- **Migration 12 required**: Drop `review_candidates`/`suppressed_candidates`/`image_review_candidates` FKs on `source_segments` before V1 table removal
- Farfetch chart FNs (8) require Vision API; accepted gap unless production has OPENAI_API_KEY
- 3 residual Snowflake FPs (value_mismatch 702 vs 948, 1 duplicate) — separate pattern, low priority

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 65 lines - distill, don't dump.

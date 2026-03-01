# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-15–22.5 + WP-21 + Migration 12 (2026-02-28)**:
- WP-15: `_rule_tier_qualifier` — Snowflake tier FPs 22→3
- WP-17: `_rule_dollar_threshold_customer` — Slack ">$100K" FPs eliminated; Slack F1 77.1%→92.3%
- Gold standard: **P=92.8%, R=77.6%, F1=84.5%** (all per-company gates passed)
- WP-18+19: Batch script hardened; `.env.template` updated
- WP-20: `logging_config.py` — JSON structured logging, optional Sentry hook
- WP-21: V2 review UI parity — `review_v2.py`, `api_v2.py`, `v2_stats.html` complete
- WP-22: `compare_v1_v2_results.py` — V1/V2 DB-based comparison script
- Migration 12: `sql/12_drop_v1_fk_constraints.sql` — drops FK deps on `source_segments`

**WP-10–14 (2026-02-24)**: Table resilience, batch hardening, review_status preservation

## Current Focus

- WP-23: Batch V2 extraction on remaining 8 filings (all prerequisites complete ✓)

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

- **Migration 12 created but not yet applied**: Run `python3 scripts/apply_migrations.py` before V1 table removal
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

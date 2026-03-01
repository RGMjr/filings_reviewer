# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**WP-24: Register Farfetch + Snowflake + re-run full batch (2026-02-28)**:
- Created `sql/register_gold_standard_filings.sql` to register Farfetch (filing_id=297, F-1) and Snowflake (filing_id=298, S-1)
- Batch ran 4/4 filings, 0 failures, 111 total facts in 14.4s
- Results: Slack 43 facts, Samsara 2 facts, Farfetch 27 facts, Snowflake 39 facts
- Snowflake: many grid-gap warnings (complex colspan tables) but extraction completed successfully
- All 4 gold standard filings now have V2 facts in DB
- Summary: `logs/batch_v2_summary_20260301_034748.json`

**WP-23: Batch V2 extraction (2026-03-01)**:
- Batch script ran successfully on 2 registered filings (Slack 295, Samsara 296)
- Results: 2/2 succeeded, 45 total facts (Slack: 43, Samsara: 2), 7.8s elapsed
- Fixed 3 persistence bugs: (1) `Document.doc_id` was set to `str(filing_id)` instead of UUID; (2) `ON CONFLICT` expression had no matching unique index — replaced with delete-then-insert; (3) `v2_metric_definitions` table missing — applied migration 11
- Summary: `logs/batch_v2_summary_20260301_033805.json`

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

- Next: Promote V2 to production (merge v2-rewrite → main, cut over review UI, retire V1 extraction)

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
- V2 persistence bugs fixed in WP-23: `ingestion.py` was setting `Document.doc_id=str(filing_id)` (should be UUID); `v2_metric_facts` ON CONFLICT expression had no matching unique index (replaced with delete-then-insert); migration 11 (`v2_metric_definitions`) was not applied

## Blockers or Warnings

- Snowflake tables have many colspan/grid-gap warnings — extraction works but may have binding gaps; accepted for now
- Farfetch chart FNs (8) require Vision API; accepted gap unless production has OPENAI_API_KEY
- 3 residual Snowflake FPs (value_mismatch 702 vs 948, 1 duplicate) — separate pattern, low priority
- `metric_values` (V1) table is empty — V1/V2 comparison script needs V1 extraction run first

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 65 lines - distill, don't dump.

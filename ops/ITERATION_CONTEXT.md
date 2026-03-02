# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Branch cleanup (2026-03-01)**:
- Preserved `.claude/teams/extraction-team.md`, `.claude/teams/refactor-team.md`, `.claude/rules/agent-dispatch.md`, `config/extraction_patterns.txt` from `claude/agent-swarm-invocation-uM0tR`
- Committed to v2-rewrite (`dff3b35`), pushed
- Deleted both stale remote branches: `claude/custom-dev-agents-BCEuT`, `claude/agent-swarm-invocation-uM0tR`

**V2 Production Promotion (2026-03-01)**:
- Merged PR #27 (v2-rewrite → main) via merge commit `2dd707e` — 155 commits
- UI cutover: `GET /` now redirects to `/v2/review/filings`; navbar updated (V2 primary, V1 secondary)
- Shared modules extracted: `src/shared/keyword_config.py`, `src/shared/models.py`
- V1 retirement: 12 extraction modules deleted, 8 scripts deleted, 31 test files deleted
- Kept for later migration: `src/extraction/{html_segmenter,exceptions,validators}.py` (fresh_extractor.py dependency)
- Gold standard: P=89.4%, R=63.2%, F1=74.1% (V1 baseline — no regression from code moves)
- Unit tests: 3280 passed, 8 skipped, 78.96% coverage (75% minimum met)

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

**WP-15–22.5 (2026-02-28)**: FP rules, batch hardening, logging, UI parity, V1/V2 comparison script
- Gold standard: **P=92.8%, R=77.6%, F1=84.5%**; Migration 12: drop V1 FK constraints

## Current Focus

- Migrate `src/gold_standard/fresh_extractor.py` from V1 HTMLSegmenter to V2 pipeline
- Full universe batch run (12 production filings beyond the 4 gold standard)
- Delete remaining V1 shims in `src/extraction/` once fresh_extractor is migrated

## Test Status

- Unit tests: 1,110 extraction_v2; full suite ~4,765 (coverage 87%)
- V2 gold standard: P=92.8%, R=77.6%, F1=84.5% (2026-02-28, post-WP-15+17)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1%

## Key Learnings for Next Iteration

- V2 persistence bugs (WP-23): `Document.doc_id` must be UUID not `str(filing_id)`; `v2_metric_facts` ON CONFLICT had no unique index — use delete-then-insert; apply migration 11 before batch
- WP-22 comparison script uses `resolve_to_canonical()` from `src/extraction/keyword_config.py`
- `source_segments` has FK deps in migrations 07/08/09 — requires migration 12 before dropping

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

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

**Full Universe Batch Run (2026-03-03)**:
- Created `scripts/register_manifest_filings.py` — reads manifest, fetches EDGAR metadata, registers companies + filings
- Registered 78 manifest filings (all `is_in_scope_phase1=True`, `processing_status='pending'`); 0 failures
- Paginated submissions fallback added: 16 old filings not in EDGAR "recent" found via history pages
- Downloaded all 78 HTML files via `batch_download_filings.py` (78/78 fetched, 0 failed, ~30s)
- Batch V2 extraction: 84 total (78 manifest + 6 transcript stubs), 35 succeeded, 49 failed, 5 facts
  - 6 "HTML not found": transcript stubs (IDs 1-6), not S-1/F-1 filings — expected, skip
  - 32 duplicate key violations: pipeline bug — same fact inserted twice in single run (idempotency gap)
  - 11 schema errors: `v2_metric_definitions` missing (6), FK constraint on canonical_metric_id (5)
- Summary: `logs/batch_v2_summary_20260302_205713.json`

## Current Focus

- Fix V2 batch extraction failures: (1) `v2_metric_definitions` missing — migration needed; (2) FK violations on `canonical_metric_id`; (3) duplicate key in persistence — pipeline not idempotent
- Validate extraction results on filings where facts were found (5 total)

## Test Status

- Unit tests: 3282 passed, 8 skipped, 81% coverage (2026-03-03)
- V2 gold standard: P=92.8%, R=77.6%, F1=84.5% (2026-02-28, post-WP-15+17)
- V1 baseline: P=89.4%, R=63.2%, F1=74.1%

## Key Learnings for Next Iteration

- `register_manifest_filings.py`: must pass `is_post_combination=False` (and other boolean flags) — DB has NOT NULL constraint
- `get_filing_by_accession` only searches "recent" EDGAR submissions; old filings need paginated history pages (`filings.files[]` in submissions JSON)
- `.env` DATABASE_URL points to port 5433 but local Postgres is on 5432 — pass `--database-url` explicitly or fix `.env`
- V2 persistence has 3 active bugs: (1) duplicate key — same fact persisted twice; (2) `v2_metric_definitions` table missing (migration gap); (3) FK on canonical_metric_id fails for some metrics

## Blockers or Warnings

- 43/78 manifest filings failed extraction due to persistence bugs — investigate before next batch
- Snowflake tables have many colspan/grid-gap warnings — extraction works but may have binding gaps; accepted for now
- Farfetch chart FNs (8) require Vision API; accepted gap unless production has OPENAI_API_KEY

---

## Update Instructions

At the END of each iteration, before committing:

1. Move "Current Focus" item to "Last Completed" with result
2. Set new "Current Focus" from ops/DEVELOPMENT_PLAN.md
3. Update "Test Status" with coverage % and any failures
4. Add any technical discoveries to "Key Learnings"
5. Note any blockers for next iteration

Keep this file under 65 lines - distill, don't dump.

# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**v2-rewrite → main merge prep (2026-03-13)**:
- Discarded 129 contaminated working tree files (reverted commits), cleaned to known-good HEAD `5bc2a93`
- Merged `origin/main` into `v2-rewrite` with `-X ours` — no manual conflict resolution required
- Fixed merge artifact: restored `import re` in `fact_construction.py` dropped by auto-merge
- Tests: 3299 unit pass, gold standard P=95.2%/R=79.6%/F1=86.7% (no regression vs baseline)
- Pushed and opened PR #32 (v2-rewrite → main), supersedes #24/#27/#29/#31

**WIP Commit + Batch Filter Fix (2026-03-04)**:
- Fixed batch filter: `WHERE c.cik IS NOT NULL` → `WHERE f.html_storage_path IS NOT NULL` in `scripts/batch_v2_extraction.py`
- Committed all WIP: persistence ON CONFLICT fix, API route tests cleanup, SQL seed for `cm_large_customers_period_end`, ITERATION_CONTEXT
- 3,307 unit tests pass; gold standard requires live DB (not run this iteration, last result P=92.8%/R=77.6%/F1=84.5%)
- PR #29 (v2-rewrite → main) updated

**Full Universe Batch Run + Bug Fixes (2026-03-03)**:
- Fixed 3 persistence bugs; re-run: **78/84 succeeded, 771 facts extracted** (154x improvement)
- 6 "HTML not found" are Salesforce/Microsoft transcript stubs (IDs 1-6), expected
- Summary: `logs/batch_v2_summary_20260303_024229.json`

## Current Focus

- Merge PR #32 (v2-rewrite → main)
- Post-merge: run cloud deployment runbook (`docs/operations/cloud-migration-runbook.md`) to deploy V2 schema to Neon

## Test Status

- Unit tests: 3,307 passed, 8 skipped (integration tests excluded — require TEST_DATABASE_URL)
- V2 gold standard: P=92.8%, R=77.6%, F1=84.5% (2026-02-28, post-WP-15+17) — requires live DB to re-run

## Key Learnings for Next Iteration

- `ON CONFLICT DO UPDATE` on expression index requires exact COALESCE expressions matching the index definition
- Transcript stubs (IDs 1-6: Salesforce/Microsoft) have CIKs — filter by `html_storage_path IS NOT NULL` not `cik IS NOT NULL`
- `v2_metric_definitions` table required by persistence but migration 11 was not applied to production DB
- api_v2 tests: patch `src.web.routes.api_v2.get_db`; use `psycopg.errors.UniqueViolation` for 409 cases

## Blockers or Warnings

- 6 transcript stub filings (IDs 1-6) will always fail unless `html_storage_path IS NOT NULL` filter is added to batch query
- Snowflake tables have colspan/grid-gap warnings — extraction works but may have binding gaps; accepted for now
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

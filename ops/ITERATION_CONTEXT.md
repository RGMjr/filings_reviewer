# Ralph Iteration Handoff

This file provides context continuity between Ralph Loop iterations. Read first, update at end of each iteration.

---

## Last Completed

**Docs refresh + web route tests (2026-03-03)**:
- Created `tests/unit/web/test_api_v2_routes.py` — 16 tests for `POST /api/v2/decisions` + `DELETE /api/v2/decisions/<id>`; all passing
- Removed stale V1 references from 9 docs files; V1 rollback guidance updated to reflect V2-only pipeline
- fresh_extractor migrated to V2 pipeline; all V1 shims deleted (`da43eb7`, `de598f2`)

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
- Open PR: v2-rewrite → main for post-migration hardening (web route tests + docs refresh)

## Test Status

- Unit tests: 3,323 collected (81% coverage; integration tests excluded — require TEST_DATABASE_URL)
- V2 gold standard: P=92.8%, R=77.6%, F1=84.5% (2026-02-28, post-WP-15+17)

## Key Learnings for Next Iteration

- `register_manifest_filings.py`: must pass `is_post_combination=False` (and other boolean flags) — DB has NOT NULL constraint
- V2 persistence has 3 active bugs: (1) duplicate key — same fact persisted twice; (2) `v2_metric_definitions` table missing (migration gap); (3) FK on canonical_metric_id fails for some metrics
- api_v2 tests: patch `src.web.routes.api_v2.get_db`; use `psycopg.errors.UniqueViolation` for 409 cases

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

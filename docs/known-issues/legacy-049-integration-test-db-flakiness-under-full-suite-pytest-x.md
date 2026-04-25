---
autonomy: n/a
discovered: '2026-04-20'
estimated: M
id: 49
note: Resolved 2026-04-23 — cannot reproduce on main; retained in table for audit trail
severity: low
slug: integration-test-db-flakiness-under-full-suite-pytest-x
source: legacy
status: resolved
title: Integration Test DB Flakiness Under Full-Suite `pytest -x`
touches: []
updated: '2026-04-23'
---

**Resolved**: 2026-04-23 — cannot reproduce on current `main`. Five back-to-back clean runs of the full suite (4× sequential `pytest -x -q`, 1× xdist `pytest -x -q -n auto`), all green. The symptoms described below (`AdminShutdown`, `connection is lost`, deadlock in ROLLBACK) do not surface. Two commits since #49 was filed likely combine to eliminate the race: (a) `5c11593` (2026-03-30) added `_terminate_stale_connections` + atomic-TRUNCATE in the V1 `clean_extraction_db` (V1 since retired); (b) `2e5977e` (2026-04-22, #78) added `_isolate_xdist_worker_database` so each pytest-xdist worker runs against its own Postgres DB, eliminating cross-worker pool/TRUNCATE contention entirely. Under `-n0` sequential mode the shared-pool race was never re-observed.

One latent hygiene concern remains (not fixed here, not currently reproducible): `tests/integration/conftest.py::clean_db` still issues three separate TRUNCATE blocks (review tables, V2 tables, `filings`+`companies`) rather than one atomic TRUNCATE. The March 30 commit explicitly identified this pattern as the "interleaved-lock deadlock window" cause in the V1 fixture. File a follow-up if the flakiness recurs.

### Problem

Running `pytest -x -q` over the full suite (unit + integration) reproducibly
fails in the first integration test that hits the connection pool. Errors
observed: `AdminShutdown: terminating connection due to administrator
command`, `psycopg.OperationalError: the connection is lost`, and
`deadlock detected` in `ROLLBACK` during fixture teardown. The specific
test that trips varies run-to-run — during #48 work, both
`tests/integration/test_db_v2_image_methods.py::TestGetImageReviewCandidatesForFilingV2::test_returns_non_decorative_images_only`
and
`tests/integration/extraction_v2/test_batch_runner_db.py::TestBatchRunnerQueryFilings::test_query_filings_returns_expected_columns`
have surfaced. Each test passes individually. Reproduces on clean `main`
with in-flight changes stashed, so it predates #48. Distinct from resolved
issues #7/#8 (missing teardown); symptom here looks like cross-test pool
orchestration or a session-scoped fixture forcing a pool rebuild during
another test's open transaction.

The effect is that the "run `pytest -x -q` before committing" gate in
CLAUDE.md is undermined — operators have to know to fall back to
`pytest tests/unit -q` and separately exercise integration, or skip the
pre-commit check.

### Next Steps

- Reproduce deterministically: run `pytest -x -q` against the integration
  dir in isolation and bisect which test ordering triggers the admin
  shutdown.
- Inspect `tests/integration/conftest.py` `test_db_adapter` and
  `clean_db` fixtures for session-scoped lifetime vs. per-test pool use.
- Candidate fix: force `function`-scoped pools for integration tests, or
  ensure the `clean_db` fixture's `TRUNCATE` does not race with another
  test's open connection.

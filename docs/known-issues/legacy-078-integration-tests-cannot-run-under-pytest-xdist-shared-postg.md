---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 78
severity: medium
slug: integration-tests-cannot-run-under-pytest-xdist-shared-postg
source: legacy
status: resolved
title: Integration Tests Cannot Run Under pytest-xdist — Shared Postgres Fixtures
touches: []
updated: '2026-04-22'
---

### Resolution

`tests/integration/conftest.py` now gives each pytest-xdist worker its own Postgres database (`filings_analysis_test_gw0`, `_gw1`, …) via a session-autouse fixture that runs before any DB-touching fixture. The fixture rewrites `os.environ["TEST_DATABASE_URL"]` at session start so both the fixture chain and the ~13 direct `os.environ.get()` readers pick up the worker URL automatically — zero application code changes. A Postgres advisory lock in `_apply_migrations_to_test_db` serialises migration 37 (`CREATE ROLE metabase_ro` + `ALTER ROLE`) across workers so concurrent `pg_authid` writes don't trigger `tuple concurrently updated`. CI (`.github/workflows/ci.yml:185`) now runs integration tests with `-n auto`. Verified locally: two back-to-back `pytest tests/integration/ -n auto` runs pass 226/226 in ~55s (vs ~3.6 min sequential on CI).

### Original problem (for reference)

### Problem

Adding `-n auto` (or even `-n auto --dist loadfile`) to the CI integration command produces immediate fixture collisions when run against a shared Postgres service. Reproduction: `uv run pytest tests/integration/ -n auto -x -q --no-cov` against `$TEST_DATABASE_URL` fails with mixes of:

- `ForeignKeyViolation: Key (filing_id)=(22432) is not present in table "filings"` — worker A cleans up a `filings` row that worker B's `v2_documents` insert still references.
- `ForeignKeyViolation: Key (fact_id)=(…) is not present in table "v2_metric_facts"` — same pattern on `v2_review_decisions.fact_id`.
- `DID NOT RAISE ReviewedFilingError` / decision-count assertions (0 == 1) — CASCADE cleanup from one worker deletes state another worker is about to assert on.

The same suite passes cleanly 43/43 in ~2.2s sequentially. Failures span `tests/integration/extraction_v2/test_persistence{,_guard}.py`, `test_definition_persistence.py`, `test_transcript_e2e.py`, and cascade into errors in `test_db_v2_image_methods.py`, `test_batch_runner_db.py`, `test_filing_fetcher_db.py`, `test_ingest_flow.py`, `test_v2_review_workflow.py`, and `test_universe_builder_integration.py`.

Root cause: integration fixtures share Postgres state (fixed CIKs, fixed filing accessions, session-scoped seed data) without per-worker isolation. `--dist loadfile` helps with intra-file cases but still fails on cross-file shared seed (e.g. a filing row seeded in one file that another file's test insert depends on).

### Why this matters

- Integration Tests is the current required-check critical path on CI at ~3.6 min wall-clock. Parallelizing would cut merge wait to ~2.0–2.5 min — the single biggest remaining PR-latency win.
- Unit Tests already run `-n auto` (uses in-memory fixtures only), so the blocker is specific to DB-backed integration tests.

### Next Steps

1. **Per-worker DB schemas.** xdist exposes `PYTEST_XDIST_WORKER` (e.g. `gw0`, `gw1`). Thread this through `conftest.py` to create/apply migrations against a schema named after the worker, and have the DB adapter `SET search_path` to it. Cleanest long-term fix.
2. **Uniquified fixture data.** Second-best: inject `uuid4()` / worker-id suffixes into `cik`, `accession_number`, and other natural keys in `create_test_company_and_filing` and equivalents.
3. **`--dist loadgroup` with shared-state markers.** Tag tests that share seed data with a `@pytest.mark.xdist_group("filings_seed")` and let xdist keep them on one worker. Cheapest change but leaves perf on the table.
4. **Verification after fix:** run `pytest tests/integration/ -n auto -x -q` locally twice in a row against `$TEST_DATABASE_URL` with zero failures, then land the `-n auto` flag in `.github/workflows/ci.yml:184–187`.

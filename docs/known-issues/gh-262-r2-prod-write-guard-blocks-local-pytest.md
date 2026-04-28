---
id: 262
source: gh
slug: r2-prod-write-guard-blocks-local-pytest
title: R2 prod-write guard fails 10 e2e tests on a clean main during local pytest
status: resolved
severity: medium
autonomy: safe
estimated: S
touches:
  - tests/integration/extraction_v2/test_e2e_pipeline.py
  - tests/integration/extraction_v2/test_full_page_ocr_pipeline.py
  - tests/integration/extraction_v2/conftest.py
  - tests/unit/infra/test_image_storage.py
discovered: '2026-04-27'
updated: '2026-04-28'
gh_issue: 262
pr_refs:
  - 275
---

### Problem

When a developer sources `.env` (which sets `R2_BUCKET` to the prod bucket and the matching R2 creds) but does not also set `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1`, ten integration tests fail on a clean `origin/main`:

- `tests/integration/extraction_v2/test_e2e_pipeline.py` — `TestE2ESlackFiling` (4 tests), `TestE2EProvenance::test_e2e_facts_have_valid_provenance`, `TestE2ETableReconstruction::test_e2e_tables_have_header_paths`, `TestE2EPersistence::test_e2e_persistence_roundtrip`, `TestE2EIdempotency::test_e2e_idempotent_rerun`, `TestE2EPerformance` (2 tests)
- `tests/integration/test_full_page_ocr_pipeline.py::test_full_page_ocr_path_a_synthesizes_image_ocr_segments`

All fail with the same error: `Refusing R2 write — set FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 to allow.`

The R2 prod-write guard is correct and intentional (per `.claude/rules/infrastructure.md` — protects against accidental prod mutations from CLI tools). The problem is the **local-developer experience**: a clean main produces 10 failures on every `pytest -x -q` run, which masks the signal of real regressions and forces every `/commit` flow to re-verify pre-existence.

Discovered while running the full suite during legacy-115 (#260) — not new behavior; reproduces on `origin/main` HEAD.

### Next Steps

Pick one of:

- **Test-side fix (preferred):** Make the affected tests skip (or use `LocalFilesystemStorage`) when `R2_BUCKET` is set but `FILINGS_REVIEWER_ALLOW_PROD_WRITES` is not. The guard's intent is to block real R2 writes in dev; tests don't need real R2 — they should exercise the pipeline against the local cache. A pytest fixture that points the test process at `LocalFilesystemStorage` for the duration of the test would resolve all 10 cases without weakening the guard.
- **Env-side documentation:** Add a `pyproject.toml` test-env note + `CONTRIBUTING.md` line documenting that local pytest needs `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` *or* an unset `R2_BUCKET`. Cheaper but doesn't actually fix the DX — every fresh checkout will hit the same wall.

### Resolution

Fixed via test-side fixture (Option A) in PR #275.

Added `tests/integration/extraction_v2/conftest.py` with an autouse `_force_local_image_storage` fixture that clears R2 env vars (`R2_BUCKET`, `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) and calls `get_image_storage.cache_clear()` before and after each test. This redirects the pipeline to `LocalFilesystemStorage` for the duration of each test, regardless of the caller's shell environment.

The fixture covers all tests under `tests/integration/extraction_v2/` — including both `test_e2e_pipeline.py` (9 tests previously failing) and `test_full_page_ocr_pipeline.py` (1 test previously failing). The now-redundant inline `_local_image_storage` fixture was removed from `test_full_page_ocr_pipeline.py`.

The R2 prod-write guard in `R2Storage.put_bytes` is unchanged and continues to block writes in all non-test contexts. A new unit test (`TestGetImageStorageFactory::test_r2_storage_guard_fires_when_bucket_set_without_allow_writes`) asserts the guard still fires when `FILINGS_REVIEWER_ALLOW_PROD_WRITES` is absent, protecting against accidental guard removal.

All 15 previously-failing integration tests now pass under `R2_BUCKET=filings-reviewer-image-cache` + `FILINGS_REVIEWER_ALLOW_PROD_WRITES` unset.

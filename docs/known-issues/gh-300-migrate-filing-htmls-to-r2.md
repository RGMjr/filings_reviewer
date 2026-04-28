---
id: 300
source: gh
slug: migrate-filing-htmls-to-r2
title: Migrate filing HTMLs to R2 long-haul storage (architecture)
status: resolved
severity: low
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 300
pr_refs: []
note: 'Shipped src/infra/filing_storage.py + extraction call-site refactor + migration script. 79 prod rows migrated to R2 keys; html_content kept as fallback. Fetcher refactor and html_content drop deferred to follow-up fragments.'
---

### Problem

Filing source HTML is stored on local disk and read by `src/extraction_v2/stages/ingestion.py` from `filings.html_storage_path`. This couples extraction to local filesystem state and creates ongoing data-hygiene burden (see #299). Image bytes already live in R2 (`src/infra/image_storage.py`); the same pattern can apply to filing HTMLs. Storage cost is trivial (~$1/month at the current corpus size).

### Next Steps

- New `src/infra/filing_storage.py` abstraction analogous to `image_storage.py`, with `R2FilingStorage` (prod) and `LocalFilesystemFilingStorage` (dev) backends, gated by the existing `FILINGS_REVIEWER_ALLOW_PROD_WRITES` env.
- Refactor `src/extraction_v2/stages/ingestion.py` to fetch HTML via the storage abstraction (opaque storage key in `html_storage_path`) instead of `Path(...).read_text()`.
- One-time migration: upload each filing's HTML bytes to R2 under a deterministic key (e.g., `filings/<cik>/<accession>/primary.htm`) and rewrite `html_storage_path`.
- Update other consumers of `html_storage_path` (e.g., reviewer UI source-rendering).

### Resolution

Shipped `src/infra/filing_storage.py` mirroring `image_storage.py`: `FilingStorage` Protocol, `LocalFilesystemFilingStorage` (rooted at `<repo>/data/filing_cache/` or `FILING_CACHE_DIR`), `R2FilingStorage` (shares the `filings-reviewer-image-cache` bucket via the `filings/` key prefix), `get_filing_storage()` factory, and the `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` prod-write guard. Validation regex shared with `image_storage.validate_key`.

Refactored extraction call sites (`scripts/batch_v2_extraction.py:206`, `scripts/run_v2_extraction.py:resolve_html_path`) to detect `html_storage_path.startswith("filings/")` and download via the storage abstraction to a tempfile. Legacy filesystem-path and `html_content` DB-blob fallbacks are preserved.

Shipped `scripts/migrate_filing_html_to_r2.py` with two-flag prod gate (`--allow-prod` + `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1`). Source priority: `html_content` (DB) → local disk → SEC re-fetch (rate-limited). R2 upload is verified via HEAD before column UPDATE; on UPDATE failure the R2 key is left in place (orphans are cheap, lost data is not). Selector self-filters, so re-running is idempotent.

Prod migration ran 2026-04-28: **audited=79, migrated=79, sec_fetched=0, skipped=0, failed=0**. All sources from `html_content` (gh-299's worktree-relative paths and html_content fields populated were the migration source). Verified `SELECT COUNT(*) FILTER (WHERE html_storage_path NOT LIKE 'filings/%/%/%') = 0` post-apply. `html_content` retained per plan-mode decision #3.

Tests: 19 unit (`tests/unit/infra/test_filing_storage.py` — both backends, prod-write guard, factory) + 8 integration (`tests/integration/test_migrate_filing_html_to_r2.py`) + 2 integration (`tests/integration/test_run_v2_extraction_r2_resolve.py` — refactored call site). Full suite (`pytest -x -q`) green: 4331 passed, no regressions.

Docs updated: `.claude/rules/infrastructure.md` (new "Filing HTML Storage" section), `CLAUDE.md` (Database section), `docs/operations/extraction-runbook.md` (new "Migrating filing HTMLs to R2" runbook section). `tests/integration/extraction_v2/conftest.py` extended to also clear `get_filing_storage.cache_clear()` so test runs with prod `R2_BUCKET` in env are deterministic.

### Deferred follow-ups

- **`filing_fetcher.py` refactor** — newly fetched filings still land with filesystem paths in `html_storage_path`; the migration script can be re-run periodically to promote them to R2 keys. A follow-up fragment will refactor the fetcher to write R2 keys directly. Rationale for deferral: refactor changes `FilingContent.html_path` semantics, which would break `scripts/onboard_tickers.py:322,330` callers without a parallel `html_storage_key` field. Deferred to keep this PR focused.
- **Drop `html_content` column** — retained as fallback during initial soak. Follow-up fragment will drop it after ≥30 days of stable R2 reads.

### Cross-references

- gh-299 (PR #311): tactical OneDrive-path fix that populated `html_content` for the 13 affected rows, providing this migration's source data.
- Image storage parallel: `src/infra/image_storage.py`, `v2_image_assets.file_path` — same opaque-key pattern.

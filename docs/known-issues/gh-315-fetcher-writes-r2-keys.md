---
id: 315
source: gh
slug: fetcher-writes-r2-keys
title: Refactor filing_fetcher to write R2 storage keys directly
status: resolved
severity: low
autonomy: skip
estimated: M
touches:
  - src/filing_fetcher/filing_fetcher.py
  - src/infra/filing_storage.py
  - tests/integration/filing_fetcher/test_filing_fetcher_db.py
  - tests/unit/filing_fetcher/test_filing_fetcher.py
discovered: '2026-04-28'
updated: '2026-04-29'
pr_refs:
  - 329
gh_issue: 315
note: 'Fixed: fetcher now uploads to R2 via get_filing_storage().put_bytes() on every successful fetch (fresh and cache-hit), verifies via HEAD, and writes the storage key to html_storage_path. html_path preserved for in-process callers.'
---

### Problem

After gh-300 (PR for migrating filing HTML to R2 storage), newly fetched filings still land with filesystem paths in `filings.html_storage_path` because `src/filing_fetcher/filing_fetcher.py` was deferred from gh-300's PR scope. The gh-300 migration script (`scripts/migrate_filing_html_to_r2.py`) can be re-run periodically to promote these to R2 keys, but that's operational toil.

### Why deferred from gh-300

Refactoring the fetcher would change the semantics of `FilingContent.html_path` (currently a filesystem path str) — either to the R2 key, or to a parallel `html_storage_key` field. Both options break or require updates to callers like `scripts/onboard_tickers.py:322,330` which pass `content.html_path` directly to `pipeline.process(html_path=...)`. gh-300 was already medium-large; this expansion was deferred.

### Resolution

- Added `FilingContent.html_storage_key: str | None` (non-breaking; `html_path` preserved for in-process callers).
- `fetch_filing` uploads bytes via `get_filing_storage().put_bytes()` immediately after the final local write (handles both fresh downloads and cache-hits). HEAD verify before DB UPDATE; fail-closed on verify failure.
- `_update_database` writes `html_storage_key` to `html_storage_path` instead of the filesystem path.
- Tests updated: assertion shape flipped from filesystem paths to storage keys; new `filing_storage` autouse fixture in unit tests clears lru_cache and patches storage; two new tests cover cache-hit and R2-failure paths.

### Deferred

Drop of read-side legacy-path detection branches in `scripts/batch_v2_extraction.py` and `scripts/run_v2_extraction.py` is deferred for one soak-window release. Dropping `filings.html_content` column is gh-314.

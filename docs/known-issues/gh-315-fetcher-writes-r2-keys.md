---
id: 315
source: gh
slug: fetcher-writes-r2-keys
title: Refactor filing_fetcher to write R2 storage keys directly
status: open
severity: low
autonomy: skip
estimated: M
touches: ['src/filing_fetcher/filing_fetcher.py', 'tests/integration/filing_fetcher/*']
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 315
note: 'Newly fetched filings still get filesystem paths in html_storage_path post-gh-300; re-running the migration script promotes them to R2 keys. Refactor the fetcher to write R2 keys directly.'
---

### Problem

After gh-300 (PR for migrating filing HTML to R2 storage), newly fetched filings still land with filesystem paths in `filings.html_storage_path` because `src/filing_fetcher/filing_fetcher.py` was deferred from gh-300's PR scope. The gh-300 migration script (`scripts/migrate_filing_html_to_r2.py`) can be re-run periodically to promote these to R2 keys, but that's operational toil.

### Why deferred from gh-300

Refactoring the fetcher would change the semantics of `FilingContent.html_path` (currently a filesystem path str) — either to the R2 key, or to a parallel `html_storage_key` field. Both options break or require updates to callers like `scripts/onboard_tickers.py:322,330` which pass `content.html_path` directly to `pipeline.process(html_path=...)`. gh-300 was already medium-large; this expansion was deferred.

### Next Steps

- Add `FilingContent.html_storage_key` field (non-breaking; preserves existing `html_path` semantics for callers).
- After fetching the HTML, upload to R2 via `get_filing_storage().put_bytes(key, bytes)` with `content_type='text/html'`. Verify via HEAD before completing fetch.
- Update `_update_database` (line ~517) to write the storage key (not the filesystem path) to `filings.html_storage_path`.
- Local dev: when `R2_BUCKET` is unset, `LocalFilesystemFilingStorage` writes to `data/filing_cache/`; `html_storage_path` still gets a key, not a path. Update `tests/integration/filing_fetcher/test_filing_fetcher_db.py` fixtures.
- After the fetcher refactor lands and bakes for a release, drop the legacy filesystem-path detection branches from `scripts/batch_v2_extraction.py:206` and `scripts/run_v2_extraction.py:resolve_html_path` (only needed during the transition).

### Operational impact

Until this lands, re-run `python3 scripts/migrate_filing_html_to_r2.py --apply` weekly (or after onboarding new tickers) to promote freshly fetched rows to R2 keys. The selector self-filters, so re-runs are idempotent and cheap.

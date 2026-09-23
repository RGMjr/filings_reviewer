---
id: 314
source: gh
slug: drop-filings-html-content-column
title: Drop filings.html_content column after R2 soak window
status: archived
severity: low
autonomy: n/a
estimated: S
touches: ['sql/*', 'scripts/batch_v2_extraction.py']
discovered: '2026-04-28'
updated: '2026-05-05'
gh_issue: 314
pr_refs:
  - 505
note: 'Drop the DB-blob fallback after gh-300 (R2 storage) bakes for ≥30 days without incident. Schema migration + remove fallback branches in extraction scripts.'
---

### Problem

After gh-300 (PR for migrating filing HTML to R2 storage), `filings.html_content` is retained as a fallback so extraction can degrade gracefully if R2 reads have issues. Once R2 has been the source of truth for ≥30 days without incident, the column should be dropped to:

- Reduce Neon DB size (~225 MiB across 79 rows currently; would grow as new filings get migrated).
- Eliminate confusion about "which is source of truth" — currently the extraction call sites prefer R2 keys but fall back to `html_content`, which could mask a real R2 outage.

### Next Steps

- Confirm ≥30 days of stable R2 reads via a query like `SELECT COUNT(*) FROM v2_documents WHERE created_at > NOW() - INTERVAL '30 days'` cross-referenced with R2 access logs / errors.
- Schema migration: `ALTER TABLE filings DROP COLUMN html_content;`. Use the timestamped-filename convention per `.claude/rules/sql.md` and `scripts/new_migration.py`.
- Drop the DB-fallback branches from `scripts/batch_v2_extraction.py:226-244` and `scripts/run_v2_extraction.py` (if extant).
- Update `.claude/rules/infrastructure.md` "Filing HTML Storage" section to remove the "html_content fallback" mention.

### Resolution

Migration `sql/202605051429_drop_html_content_column.sql` drops the column with `ALTER TABLE filings DROP COLUMN IF EXISTS html_content`.

Call sites updated:
- `src/filing_fetcher/filing_fetcher.py` — removed `html_content` field from `FilingContent`, removed DB write in `_update_database`, removed DB-fallback read in `_get_cached_filing`
- `scripts/batch_v2_extraction.py` — removed DB-fallback block (was lines 251–275)
- `scripts/backfill_text_presence.py` — replaced DB fallback in `_resolve_html` with R2 storage lookup via `get_filing_storage()`
- `scripts/audit_filing_url_mismatch.py` — removed `html_content_len` / `html_content_head` from SQL query and removed `_sniff_html_content_column` function
- `.claude/rules/infrastructure.md` — updated Filing HTML Storage reader-side paragraph

Integration tests for historical migration scripts that read/write `html_content` (`test_migrate_filing_html_to_r2.py`, `test_migrate_onedrive_html_paths.py`) were deleted — those scripts are permanent historical artifacts and cannot run after the column is dropped.

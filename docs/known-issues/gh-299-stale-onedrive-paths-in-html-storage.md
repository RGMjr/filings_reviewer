---
id: 299
source: gh
slug: stale-onedrive-paths-in-html-storage
title: Stale OneDrive paths in filings.html_storage_path block re-extraction
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 299
pr_refs: []
note: 'Migration script rewrote 13 prod rows from /Users/.../OneDrive-CMASB/... paths to worktree-relative form and populated html_content from disk; superseded by gh-300 (R2 storage migration).'
---

### Problem

5 filings (filing_ids 1539, 1544, 1546, 1548, 1551 — Datadog, Maplebear, Samsara, Slack, Torrid) carry `filings.html_storage_path` values under `/Users/.../OneDrive-CMASB/.../data/gold_standard/<Company>/filing.html` with NULL `html_content`. OneDrive cloud-only files are no longer reliably hydrated locally; 3 of these 5 timed out during a 2026-04-28 backfill (`Operation timed out`), 2 happened to be hydrated and succeeded. Canonical local copies all exist at `data/gold_standard/<Company>/filing.html` (2–5 MB each). Likely broader than these 5 — any filing ingested before the OneDrive→local migration may share the pattern.

### Next Steps

- Audit `filings` for `html_storage_path LIKE '/Users/%/OneDrive-CMASB/%'`. Count + report scope.
- Migration script to rewrite paths to the worktree-relative form, verifying each rewritten path resolves to a real file. Fall back to `sec_html_url` fetch for missing files.
- Optionally populate `html_content` from disk so re-extraction does not depend on file paths.

### Resolution

Shipped `scripts/migrate_onedrive_html_paths.py` (CLI with `--dry-run`/`--apply`/`--allow-prod` plus `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` env gate, mirroring `scripts/relink_paypal_r2_keys.py`). Audit found **13** affected rows (broader than the fragment's 5 — also Chewy, Farfetch, Flywire, GitLab, Kingsoft, Samsara Vision, Snowflake, Tenable). All 13 had local canonical copies in `data/gold_standard/<Company>/filing.html` (1.9–5.3 MB each); the SEC re-fetch fallback path was not exercised.

Prod migration ran 2026-04-28 against Neon: **audited=13, rewritten=13, fetched_from_sec=0, failed=0**. Each row's `html_storage_path` was rewritten to the worktree-relative form (`data/gold_standard/<Company>/filing.html`) and `html_content` populated from disk in a per-filing transaction. Verified `SELECT COUNT(*) ... LIKE '/Users/%/OneDrive-CMASB/%'` = 0 post-apply.

Recovery procedure documented at `docs/operations/extraction-runbook.md` ("Recovering filings with stale storage paths"). Tests at `tests/integration/test_migrate_onedrive_html_paths.py` cover dry-run, disk-apply, SEC fallback, both prod-host guards, and idempotency.

This is a tactical fix; gh-300 will replace `html_storage_path` semantics with R2 storage keys, superseding the worktree-relative path format shipped here.

---
id: 299
source: gh
slug: stale-onedrive-paths-in-html-storage
title: Stale OneDrive paths in filings.html_storage_path block re-extraction
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 299
note: '5 known filings (and likely more corpus-wide) carry html_storage_path values under /Users/.../OneDrive-CMASB/... with NULL html_content; ingestion times out when files are not hydrated.'
---

### Problem

5 filings (filing_ids 1539, 1544, 1546, 1548, 1551 — Datadog, Maplebear, Samsara, Slack, Torrid) carry `filings.html_storage_path` values under `/Users/.../OneDrive-CMASB/.../data/gold_standard/<Company>/filing.html` with NULL `html_content`. OneDrive cloud-only files are no longer reliably hydrated locally; 3 of these 5 timed out during a 2026-04-28 backfill (`Operation timed out`), 2 happened to be hydrated and succeeded. Canonical local copies all exist at `data/gold_standard/<Company>/filing.html` (2–5 MB each). Likely broader than these 5 — any filing ingested before the OneDrive→local migration may share the pattern.

### Next Steps

- Audit `filings` for `html_storage_path LIKE '/Users/%/OneDrive-CMASB/%'`. Count + report scope.
- Migration script to rewrite paths to the worktree-relative form, verifying each rewritten path resolves to a real file. Fall back to `sec_html_url` fetch for missing files.
- Optionally populate `html_content` from disk so re-extraction does not depend on file paths.

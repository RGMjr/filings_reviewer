---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 30
severity: n/a
slug: 15-filings-with-cik-sec-html-url-mismatch
source: legacy
status: archived
title: 15 Filings With CIK / sec_html_url Mismatch
touches: []
updated: '2026-04-22'
---

`scripts/audit_filing_url_mismatch.py` enumerated affected rows; `scripts/repair_filing_url_mismatch.py --path A --apply` corrected all 15 `sec_html_url` values. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`. Latent cached-HTML residue tracked as Issue #43. See git log (2026-04-19).

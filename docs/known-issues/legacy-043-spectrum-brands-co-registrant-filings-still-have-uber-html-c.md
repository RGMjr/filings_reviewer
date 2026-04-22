---
autonomy: skip
discovered: '2026-04-19'
estimated: —
id: 43
note: Latent; no action needed until re-extraction
severity: low
slug: spectrum-brands-co-registrant-filings-still-have-uber-html-c
source: legacy
status: open
title: Spectrum Brands Co-Registrant Filings Still Have Uber HTML Cached on Disk
touches: []
updated: '2026-04-19'
---

### Problem

Filing_ids 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 913, 914, 915, 916, 919 all point `html_storage_path` at `data/filings/0001725792/000119312519149408/primary.htm`. That file contains **Uber S-1/A content**, not the Spectrum Brands 2019 S-1/A content these rows represent (accession `0001193125-19-149408`, co-registered by 15 Spectrum Brands entities). Root cause is the same pre-Issue-#6 FilingFetcher mis-save that caused Issue #30 — the URL column was fixed by the #30 resolution, but the cached HTML file was not replaced.

### Why it's latent, not active

All 15 rows have `v2_metric_facts_count = 0`, `v2_review_decisions_count = 0`, `v2_image_review_decisions_count = 0`. No extraction has run on these filings, so no facts are derived from the wrong HTML. Reviewer-facing UI links point to the correct SEC documents (fixed in Issue #30). The problem would only surface if/when someone runs `scripts/batch_v2_extraction.py` against these filing_ids — they'd get Uber facts attributed to Spectrum Brands.

### Next Steps

Pick one:

1. **Refetch once, update all 15** (preferred): Call `FilingFetcher.fetch_filing()` for one co-registrant (e.g., the primary Spectrum Brands CIK `0001028985`) with the correct resolved URL, writing to a new storage path under `data/filings/0001028985/000119312519149408/primary.htm`. Then `UPDATE filings SET html_storage_path = <new path>, html_content = NULL WHERE filing_id IN (902, 903, ..., 919)`. Force-reextract not needed because `facts=0`.
2. **Delete the stale file + clear paths**: Just `UPDATE filings SET html_storage_path = NULL, html_content = NULL, html_fetched_at = NULL, processing_status = 'pending' WHERE filing_id IN (...)` and let the normal `FilingFetcher` flow re-download on next run. Simpler, but reverts processing_status.
3. **Remove from universe**: if Spectrum Brands debt-securities S-1/A is not actually in scope for customer-metrics analysis (these are consumer-goods entities, not tech/SaaS), consider deleting the 15 rows entirely — safe here because `facts=0 AND reviews=0`.

### Context

See Issue #30 resolution notes (now in archive) for full audit trail. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`.

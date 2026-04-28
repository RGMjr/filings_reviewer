---
id: 300
source: gh
slug: migrate-filing-htmls-to-r2
title: Migrate filing HTMLs to R2 long-haul storage (architecture)
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 300
note: 'Apply the existing R2 image-bytes pattern to filing HTMLs to remove local-disk / OneDrive dependency from extraction.'
---

### Problem

Filing source HTML is stored on local disk and read by `src/extraction_v2/stages/ingestion.py` from `filings.html_storage_path`. This couples extraction to local filesystem state and creates ongoing data-hygiene burden (see #299). Image bytes already live in R2 (`src/infra/image_storage.py`); the same pattern can apply to filing HTMLs. Storage cost is trivial (~$1/month at the current corpus size).

### Next Steps

- New `src/infra/filing_storage.py` abstraction analogous to `image_storage.py`, with `R2FilingStorage` (prod) and `LocalFilesystemFilingStorage` (dev) backends, gated by the existing `FILINGS_REVIEWER_ALLOW_PROD_WRITES` env.
- Refactor `src/extraction_v2/stages/ingestion.py` to fetch HTML via the storage abstraction (opaque storage key in `html_storage_path`) instead of `Path(...).read_text()`.
- One-time migration: upload each filing's HTML bytes to R2 under a deterministic key (e.g., `filings/<cik>/<accession>/primary.htm`) and rewrite `html_storage_path`.
- Update other consumers of `html_storage_path` (e.g., reviewer UI source-rendering).

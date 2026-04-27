---
autonomy: safe
discovered: '2026-04-27'
estimated: S
id: 115
severity: low
slug: 8k-exhibit-99-1-pdf-format-silently-skipped
source: legacy
status: open
title: 8-K Exhibit 99.1 in PDF Format is Silently Skipped
touches:
- src/infra/sec_client.py
- src/filing_fetcher/filing_fetcher.py
updated: '2026-04-27'
---

### Problem

`SECClient.get_exhibit_99_1_url` (added in legacy-058 fix) only matches `.htm` / `.html` filenames when scanning EDGAR `index.json`. If a filer submits exhibit 99.1 as a PDF (e.g. `exhibit99-1.pdf`), the method returns `None` and `FilingFetcher.fetch_filing` silently proceeds with the primary-only content. No warning is emitted. PDF-format earnings releases are not uncommon for some smaller or older filers.

### Next Steps

- Extend `get_exhibit_99_1_url` to also match `.pdf` filenames via the existing `_EXHIBIT_991_RE` regex.
- In `FilingFetcher.fetch_filing`, if the exhibit URL resolves to a `.pdf`, attempt a text extraction pass (e.g. via `pdfminer` or the existing OCR path) and append the extracted text to the combined HTML. Alternatively log a warning and skip — the warning is the minimum acceptable fix so operators can identify affected filings.
- Add a test case: `get_exhibit_99_1_url` returns a `.pdf` URL when only a PDF exhibit is listed in the index.

---
autonomy: review
discovered: '2026-04-20'
estimated: S
id: 58
note: 8-K Exhibit 99.1 fetch; feature add, needs validator run
severity: medium
slug: 8-k-fetcher-returns-only-primary-doc-earnings-content-lives
source: legacy
status: resolved
title: 8-K Fetcher Returns Only Primary Doc; Earnings Content Lives in Exhibit 99.1
touches:
- src/filing_fetcher/*.py
- src/infra/sec_client.py
- tests/integration/filing_fetcher/test_8k_exhibit_fetch.py
updated: '2026-04-27'
---

### Problem

`FilingFetcher.fetch_filing` (`src/filing_fetcher/filing_fetcher.py:263-365`) downloads only `primary.htm` resolved from the accession's directory URL. For many 8-K filings the primary doc is a ~10 KB cover page that points at Exhibit 99.1 (the actual press release / financial-highlights HTML). Pipeline ran cleanly on 4/5 Phase 0 candidates but Samsara (2025-08-21) produced 0 facts — the primary doc was 9,336 bytes of boilerplate; all customer-metric content sat in `exhibit991-2025x08x21.htm` which was never fetched.

### Next Steps

1. In `fetch_filing`, after downloading `primary.htm`, parse the index for `99.1` (or regex-matched variants like `ex-99-1`) and download the exhibit alongside the primary doc.
2. Decide whether the pipeline consumes only the exhibit, both docs concatenated, or runs twice and merges facts — prefer "concat with a section break" for the MVP to avoid invalidating `filing_id` uniqueness.
3. Add an integration test using the Samsara 8-K (or a fixture mirroring its structure) asserting >0 customer-metric facts.
4. Gate on this before enabling 8-K in the batch-ingest UI form-type selector.

---
autonomy: safe
discovered: '2026-04-24'
estimated: M
id: 104
severity: medium
slug: presentation-accession-prefix-breaks-v2-image-urls
source: legacy
status: open
title: '"presentation:" / "transcript:" Accession Prefix Blocks V2 Image Fetcher'
touches:
  - src/infra/sec_client.py
  - src/extraction_v2/stages/ocr_extraction.py
  - src/web/url_builders.py
updated: '2026-04-24'
---

### Problem

Filings ingested via `ingest_presentations.py` store `accession_number` in a
synthetic format (`presentation:0001633917/0001633917-23-000070/q123file.htm`)
rather than the bare `NNNNNNNNNN-NN-NNNNNN` SEC token. When the V2 OCR stage
calls `SECClient.fetch_image(cik, accession, filename)`, the accession string
is inserted into the EDGAR URL path verbatim, producing malformed URLs like
`https://www.sec.gov/Archives/edgar/data/CIK/presentation:0001633917/...` →
every request 404s.

Observed today: all 13 chart-bearing PayPal 8-K presentations (filing_ids
1747–1759) failed every image fetch, so the new `ImageClassifyStage` had
zero candidates after the `file_path IS NOT NULL` filter. The V2 image
pipeline effectively cannot run on any filing ingested through the
presentation or transcript paths.

### Next Steps

- Extract the bare accession token (`re.search(r'\d{10}-\d{2}-\d{6}',
  accession_number)`) in the image-URL construction paths, matching the
  pattern sql/41 applies to the `filings.accession_number` backfill.
- Or: store the synthetic key in a new column (`synthetic_accession` or
  `source_id`) and keep `accession_number` strictly the bare SEC token.
- Add an integration test that runs a presentation-ingested filing through
  the V2 pipeline with `enable_metric_classify=True` and asserts chart
  downloads succeed.

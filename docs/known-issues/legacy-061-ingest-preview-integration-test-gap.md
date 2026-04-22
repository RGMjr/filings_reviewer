---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 61
severity: n/a
slug: ingest-preview-integration-test-gap
source: legacy
status: archived
title: '`/ingest/preview` Integration-Test Gap'
touches: []
updated: '2026-04-22'
---

`POST /ingest/preview` was only covered by unit tests on the form-parser helpers.
Added `TestIngestPreview` to `tests/integration/web/test_ingest_flow.py` with three tests:
three-bucket split assertion (new / already-extracted no-review / already-reviewed),
volume-banner alert-class check (`alert-success` for ≤49 filings via `_volume_band_alert_class`),
and hidden-`filing_id` field survival assertion. Seeds two 10-K filings via
`create_test_company_and_filing`; reuses existing `client`/`db_adapter` fixtures.

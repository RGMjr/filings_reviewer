---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 22
severity: n/a
slug: no-reviewed-filing-guard-on-image-re-extraction
source: legacy
status: archived
title: No Reviewed-Filing Guard on Image Re-Extraction
touches: []
updated: '2026-04-22'
---

Narrow image-side guard added to `_persist_images_in_tx` in `src/extraction_v2/persistence.py`: fires when a decided image would be re-classified from the visible set (`chart`/`table_image`/`unknown`) into the hidden set (`decorative`/`logo`/`signature`); `force=True` proceeds with structured warning. `ReviewedFilingError` gained optional `context` kwarg. 5 new tests in `tests/integration/extraction_v2/test_persistence_guard.py::TestGuardOnPersistImages`. See git log (2026-04-18).

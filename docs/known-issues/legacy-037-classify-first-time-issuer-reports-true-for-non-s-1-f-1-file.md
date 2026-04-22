---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 37
severity: n/a
slug: classify-first-time-issuer-reports-true-for-non-s-1-f-1-file
source: legacy
status: archived
title: '`classify_first_time_issuer` Reports `True` for Non-S-1/F-1 Filers'
touches: []
updated: '2026-04-22'
---

`_process_filing` in `src/universe/universe_builder.py` gates `classify_first_time_issuer` on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`; non-S-1/F-1 filings land with `is_first_time_issuer=NULL`. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`. See commit `366d9dd`.

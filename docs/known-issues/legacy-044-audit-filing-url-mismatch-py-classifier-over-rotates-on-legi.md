---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 44
severity: n/a
slug: audit-filing-url-mismatch-py-classifier-over-rotates-on-legi
source: legacy
status: archived
title: '`audit_filing_url_mismatch.py` Classifier Over-Rotates on Legitimate Co-Registrant
  Sharing'
touches: []
updated: '2026-04-22'
---

`_classify_path` decision tree refined: `facts==0` short-circuits to Path A; `facts>0` + collision routes to new `B_coordinated` sub-path. `repair_filing_url_mismatch.py` warns on `B_coordinated` rows. 7 unit tests at `tests/unit/scripts/test_audit_filing_url_mismatch.py`. See git log (2026-04-20).

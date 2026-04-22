---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 31
severity: n/a
slug: audit-log-spams-dns-error-in-test-dev
source: legacy
status: archived
title: Audit Log Spams DNS Error in Test / Dev
touches: []
updated: '2026-04-22'
---

Both async (`src/web/routes/review_unified.py:97-109`) and sync (`src/web/middleware.py:87-120`) audit-log paths downgrade `ERROR` to `DEBUG` when `TESTING=True`. Covered by `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging`. See commit `366d9dd`.

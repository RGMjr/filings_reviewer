---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 50
severity: n/a
slug: no-401-path-test-coverage-for-api-unified-bp
source: legacy
status: archived
title: No 401-Path Test Coverage for `api_unified_bp`
touches: []
updated: '2026-04-22'
---

New `tests/unit/web/test_api_unified_auth.py` — 6 cases covering missing/wrong/correct key, query-arg + same-origin Referer bypass, and `API_KEY_REQUIRED`-without-`API_KEY` misconfig. Mirrors `TestImageCropAuth` shape. Target endpoint: `DELETE /api/v2/decisions/<decision_id>` with mocked DB. See commit `7848605`.

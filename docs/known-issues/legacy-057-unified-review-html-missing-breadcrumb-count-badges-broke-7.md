---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 57
severity: n/a
slug: unified-review-html-missing-breadcrumb-count-badges-broke-7
source: legacy
status: archived
title: '`unified_review.html` Missing Breadcrumb + Count Badges Broke 7 Playwright
  Tests'
touches: []
updated: '2026-04-22'
---

Bootstrap breadcrumb nav and `badge bg-success`/`badge bg-danger` accepted/rejected count spans added to `src/web/templates/unified_review.html`; 2 test selectors updated in `tests/ui/review.spec.js` (`.fact-metric-id` + `.fs-5.fw-bold`). All 151 UI tests pass. See git log (2026-04-21).

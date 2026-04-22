---
autonomy: skip
discovered: '2026-04-21'
estimated: S
id: 75
note: Playwright E2E gap — cross-filing auto-advance; needs stub-server extension
severity: low
slug: missing-playwright-e2e-for-cross-filing-auto-advance
source: legacy
status: open
title: Missing Playwright E2E for Cross-Filing Auto-Advance
touches:
- tests/ui/*.spec.js
- tests/ui/test_server.py
updated: '2026-04-21'
---

### Problem

The "auto-advance to next filing when queue empties" behavior is tested at the route-plumbing layer (`tests/unit/web/test_review_v2_routes.py::test_next_filing_preserves_sort_order` and siblings) but not at the browser layer. A regression in `unified_review.html:~1047` (text completion) or `review_images_v2.js:navigateAfterQueueEmpty` would slip past current CI. Prior regressions of this behavior (commits `5f16360`, `34ec47e`) are the reason this PR exists.

### Next Steps

- Add a Playwright spec in `tests/ui/` that seeds two filings with pending facts, sets sort to `company asc` on the list, approves the last pending fact in filing A, and asserts the browser lands on filing B (not the list, not default date-desc order).
- Repeat the assertion with image-queue completion as the trigger (relevant → non-relevant → skip the last image).
- Reuse the stub-server pattern in `tests/ui/test_server.py`; extend it with a `/filings-list-stub` route that renders `unified_filing_list.html` with two seeded filings.

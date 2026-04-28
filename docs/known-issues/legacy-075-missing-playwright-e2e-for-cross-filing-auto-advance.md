---
autonomy: skip
discovered: '2026-04-21'
estimated: S
id: 75
note: Text-queue variant landed in PR #178; image-queue variant remains open
pr_refs:
  - 178
severity: low
slug: missing-playwright-e2e-for-cross-filing-auto-advance
source: legacy
status: partially-resolved
title: Missing Playwright E2E for image-queue cross-filing auto-advance
touches:
- tests/ui/*.spec.js
- tests/ui/test_server.py
updated: '2026-04-28'
---

### Original problem

The "auto-advance to next filing when queue empties" behavior is tested at the route-plumbing layer (`tests/unit/web/test_review_v2_routes.py::test_next_filing_preserves_sort_order` and siblings) but not at the browser layer. A regression in `unified_review.html:~1047` (text completion) or `review_images_v2.js:navigateAfterQueueEmpty` would slip past current CI. Prior regressions of this behavior (commits `5f16360`, `34ec47e`) are the original motivation for this fragment.

### Resolved (text-queue variant)

PR #178 (commit `ecc8b30`, 2026-04-24) added `tests/ui/review.spec.js` test 19 ("text-queue completion navigates to next filing") covering the text-fact path.

### Remaining (image-queue variant)

The image-queue completion variant is still missing. `tests/ui/review.spec.js:1136` carries an explicit `// Image-queue completion variant deferred` stub. Implementing it requires extending the stub-server XHR catch-all in `tests/ui/test_server.py` to handle the image confirmation endpoints; PR #178's scope cut left this undone.

### Next steps

- Implement the image-queue variant: seed two filings with pending image confirmations, confirm the last image in filing A (relevant → non-relevant → skip), and assert the browser lands on filing B preserving sort order.
- Extend the stub-server XHR catch-all in `tests/ui/test_server.py` to handle the `/api/v2/image-confirmation/*` endpoints.

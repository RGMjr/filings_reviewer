---
autonomy: n/a
discovered: '2026-04-21'
estimated: S
id: 75
note: Text-queue variant landed in PR #178; image-queue variant landed in follow-up PR
pr_refs:
  - 178
severity: low
slug: missing-playwright-e2e-for-cross-filing-auto-advance
source: legacy
status: resolved
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

### Resolution (image-queue variant)

The image-queue variant landed as test 19 ("image-queue completion navigates to next filing") in `tests/ui/review.spec.js`. Implementation differed slightly from the original "Next steps" sketch:

- The test mirrors the text-queue test pattern by intercepting the API call (`/api/v2/image-candidates/*/skip`) via `page.route` rather than extending the stub server's XHR catch-all. The fixture routes `/filing-a-images-last-pending` and `/filing-b-images-pending` (and their template-vars helpers `_cross_filing_template_vars_a_images` / `_cross_filing_template_vars_b_images`) were already in place from a prior preparatory PR.
- The `relevant → non-relevant → skip` sequence in the original sketch was reduced to a single `#btn-skip` click, which is the simplest reliable trigger of `navigateAfterQueueEmpty()` from the images tab. The "Reject all (no relevant metrics)" affordance has its own coverage; this test specifically exercises the queue-empty cross-filing branch in `submitSkip` → `navigateAfterQueueEmpty` → `window.location.href = NEXT_FILING_URL`.
- Init-time XHR (`/api/v2/metrics/list`) is already stubbed in `test_server.py` (added since the deferral comment was written), so `page.goto` no longer hangs on `load`.

The earlier deferral comment at `tests/ui/review.spec.js:1137` is removed.

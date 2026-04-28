---
id: 293
source: gh
slug: image-card-undo-review-affordance
title: "Image card: 'Undo review' / re-open affordance"
status: resolved
severity: medium
autonomy: skip
estimated: S
touches:
  - src/web/routes/api_unified.py
  - src/web/routes/review_unified.py
  - src/web/templates/unified_review.html
  - src/web/static/js/review_images_v2.js
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 293
pr_refs:
  - 302
note: supersedes deferred Step B of legacy-089 with cleaner scope
---

### Problem

Per-metric undo (`DELETE /api/v2/image-metric-confirmations/<id>`)
already exists, but legacy `v2_image_review_decisions` rows +
`v2_image_assets.review_status='reviewed'` decisions made before the
per-metric pivot have no UI path back to pending. Filing 1748 (PayPal
Q3'23 8-K) is the canonical case: 18 images decided pre-OCR, now have
fresh `ocr_text` attached, but the queue treats them as already
reviewed. Supersedes the deferred Step B of legacy-089 with cleaner
scope.

### Next Steps

- Add a single button on the image card ("Undo review" / "Re-open for
  review") that flips `v2_image_assets.review_status='pending'` and
  writes an audit row.
- Do NOT delete prior decision rows from `v2_image_review_decisions` or
  `v2_image_metric_confirmations` — preserve the per-(image, metric)
  decision trail as ML training signal (memory:
  `project_image_review_decisions_for_ml_training`).
- Decide explicitly which surface the button manipulates (image-level
  `review_status` vs. derived `image_review_state`); audit interaction
  with per-metric confirmations already in place
  (memory: `project_image_review_status_not_flipped_by_per_metric`).
- Validation target: `/v2/review/1748` — pressing the button on any of
  the 18 images should return it to the pending queue with the OCR'd
  text visible.

### Resolution

Shipped in PR #302 (merged 2026-04-28). Added an image-card "Re-open
for review" button that flips `v2_image_assets.review_status='reviewed'`
back to `'pending'` via `POST /api/v2/image-candidates/<img_id>/reopen`
(handled by `db.reopen_image_candidate_v2`). Prior decision rows in
`v2_image_review_decisions` and `v2_image_metric_confirmations` are
preserved per `project_image_review_decisions_for_ml_training`. The
button manipulates the image-level `v2_image_assets.review_status`
surface only — per-metric state is untouched.

Step B of legacy-089 (the *signal* that an image's underlying OCR /
chart data has changed since the prior decision) is the natural follow-up
and is tracked via the design doc shipped in PR #319
(`docs/architecture/image-decision-revalidation-design.md`,
recommendation: Option C — stale-OCR badge layered over this endpoint).

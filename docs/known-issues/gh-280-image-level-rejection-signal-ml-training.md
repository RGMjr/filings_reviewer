---
id: 280
source: gh
slug: image-level-rejection-signal-ml-training
title: Image-level rejection signal for ML training (zero-detected-metric images leave no row)
status: archived
severity: medium
autonomy: n/a
estimated: —
touches: []
discovered: 2026-04-28
updated: 2026-04-28
gh_issue: 280
note: zero-detected-metric "Reject all" leaves no per-metric row; need image-level negative label for relevance classifier training
---

### Problem

When a reviewer dismisses an image with zero detected metrics via "Reject all (no relevant metrics)", no row is written to `v2_image_metric_confirmations` — only `v2_image_assets.review_status='skipped'` flips, which is overloaded ("dismissed as irrelevant" vs "park for later"). For images with detected metrics, the per-metric reject rows already give clean training data; the gap is empty-detected images, which are exactly the population a future auto-rejection classifier most needs to learn from.

### Next Steps

- Decide between (a) adding `decision='reject_image'` enum value with `detected_metric_id=NULL` written for every "Reject all" press, or (b) splitting `review_status='skipped'` into `skipped_rejected` / `skipped_parked`.
- Update the "Reject all" handler to write the new signal in addition to `/skip`.
- Plan backfill for historical `skipped` rows where intent is recoverable (presence of per-metric reject rows ⇒ `skipped_rejected`).

### Resolution

Discovered already-fixed during /pick-issues triage. The sentinel-row write was implemented in commit `d855f8e` (PR #284, "feat(review-ui): visible 'no relevant metrics' rejection on image review").

End-to-end path as verified:

- **JS** (`src/web/static/js/review_images_v2.js:856-910`): when `state.detectedMetrics.length === 0`, `rejectAllUnreviewed()` composes `decisions = [{detected_metric_id: null, confirmed_metric_id: null, decision: 'reject', rejection_reason: 'no_relevant_metrics'}]` and POSTs to `/api/v2/image-metric-confirmations`.
- **API** (`src/web/routes/api_unified.py:685-690`): the `decision == "reject"` validator allows `detected_metric_id=None` only when `rejection_reason == "no_relevant_metrics"` — exactly the sentinel case.
- **DB** (`src/infra/db.py:2281-2325`): `insert_image_metric_confirmations` upserts with conflict key `COALESCE(detected_metric_id, confirmed_metric_id, '')`, admitting one sentinel row per `(img_id, reviewer_id)`.
- **`_promote_chart_fact`** (`src/infra/db.py:2368`): early-returns on `if not metric_id`, so sentinel rows never spuriously promote a fact row.

The behavior is authoritatively documented in `CLAUDE.md` Core Design Principles §4. The fragment's described gap was already closed before this issue was filed; this PR closes the tracking fragment.

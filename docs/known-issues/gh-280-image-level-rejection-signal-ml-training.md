---
id: 280
source: gh
slug: image-level-rejection-signal-ml-training
title: Image-level rejection signal for ML training (zero-detected-metric images leave no row)
status: open
severity: medium
autonomy: skip
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

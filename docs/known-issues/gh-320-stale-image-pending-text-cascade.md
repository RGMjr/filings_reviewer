---
id: 320
source: gh
slug: stale-image-pending-text-cascade
title: Stale IMAGE_PENDING in text-decision cascade may skip image-tab navigation
status: archived
severity: low
autonomy: n/a
estimated: —
touches: ["src/web/templates/unified_review.html", "src/web/routes/api_unified.py"]
discovered: 2026-04-28
updated: 2026-04-29
gh_issue: 320
---

### Problem

`unified_review.html` declares `const IMAGE_PENDING = {{ image_pending }}` at page-load. The text-decision cascade (`POST /api/v2/decisions`) uses this to decide whether to navigate to the images tab after the last pending text fact is resolved. If images are pending at page-load but the reviewer clears them all before working the text tab, `IMAGE_PENDING` stays non-zero and text-completion will attempt to redirect to the images tab even though there is nothing left there. The symmetric issue on the image side (stale `window.TEXT_PENDING`) was fixed in #313 by returning fresh counts from the image-decision API.

### Next Steps

- Add `image_pending_count` to the `POST /api/v2/decisions` response (text decisions), mirroring the #313 fix for image decisions.
- Update `submitDecision` in `unified_review.html` to refresh `IMAGE_PENDING` from the response before the cascade fires.
- Add a unit test covering the scenario where `IMAGE_PENDING` is zero at page-load but a fact decision would have otherwise tried to navigate to images.

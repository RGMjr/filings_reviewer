---
autonomy: skip
discovered: '2026-04-22'
estimated: S
id: 27
note: Stale assertions — needs judgment on test rewrite
severity: n/a
slug: images-tab-playwright-assertions-fail
source: legacy
status: archived
title: Images Tab Playwright Assertions Fail
touches: []
updated: '2026-04-22'
---

Of 3 originally failing assertions: line 965 fixed via mock `img_id` addition in commit `413b386`; the two remaining `test.skip` blocks (keyword-badge and "Image 1 of 2" in the image context panel) deleted as stale — neither element is rendered by `unified_review.html` (template renders `Image #N` only, no "of M" counter; no `.keyword-badge` class exists). Product intent confirmed: these assertions had no corresponding template markup to validate. See git log 2026-04-21.

---
id: 354
source: gh
slug: add-metric-keyboard-shortcut
title: Add keyboard shortcut for "Add metric the classifier missed" button
status: archived
severity: low
autonomy: skip
estimated: XS
touches:
  - src/web/static/js/review_images_v2.js
  - src/web/templates/unified_review.html
  - .claude/rules/web.md
discovered: 2026-04-29
updated: 2026-05-04
gh_issue: 354
pr_refs:
  - 447
note: Shift+A keyboard shortcut shipped in PR #447 — image-level keydown handler triggers #btn-add-missed-detected-metric.click(), kbd badge added to button, .claude/rules/web.md table updated.
---

### Problem

The image-tab "+ Add metric the classifier missed" button (`#btn-add-missed-detected-metric` in `unified_review.html`) currently requires a mouse click — every other per-metric and image-level action on the same card has a keyboard shortcut documented in `.claude/rules/web.md`. This breaks the otherwise-keyboard-driven review flow.

### Next Steps

- Pick a non-colliding key — likely `+` (literal) or `Shift+A` (chord; A is per-row accept).
- Wire the shortcut in `src/web/static/js/review_images_v2.js` image-level keydown handler — trigger `#btn-add-missed-detected-metric` click, then focus `#add-missed-detected-input`.
- Add `<span class="kbd ms-1">…</span>` badge to the button label.
- Update the keyboard shortcut table in `.claude/rules/web.md`.

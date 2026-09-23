---
id: 294
source: gh
slug: image-tab-keyboard-shortcut-audit
title: "Image tab: keyboard-shortcut audit + parity with text tab"
status: archived
severity: low
autonomy: n/a
pr_refs:
  - 297
estimated: S
touches:
  - src/web/templates/unified_review.html
  - src/web/static/js/review_images_v2.js
  - .claude/rules/web.md
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 294
note: align image-tab shortcuts with text-tab; add missing 'Reject all' binding
---

### Problem

Text-tab review uses single-letter shortcuts (P / N / F for prev /
next / next-filing). The image tab has its own bindings
(`review_images_v2.js`) but they have drifted vs. the text tab as new
buttons land — most recently the **Reject all (no relevant metrics)**
button (PR #284) shipped without a shortcut. Reviewers context-switching
between tabs lose muscle memory.

### Next Steps

- Tabulate all current shortcuts on both tabs (`unified_review.html` +
  `static/js/review_images_v2.js`).
- Decide the policy for destructive / bulk actions: chord (Shift+R,
  Ctrl+R) vs single-letter. Recommendation: chord for "Reject all",
  since it touches every detected metric on the image at once.
- Add the missing shortcut for "Reject all (no relevant metrics)".
- Where text and image share semantics (next/prev, next-filing), align
  on the same key.
- Document the final mapping in `.claude/rules/web.md` so future buttons
  are added with shortcuts from day one.

### Resolution

Shipped in PR #297 (merged 2026-04-28):

- Added `Shift+R` chord for "Reject all (no relevant metrics)" — chord guards against accidental bulk rejection.
- Added `N` / `P` image-level navigation aliases (parity with text tab's next/prev). Guarded so per-row `N` (focusNextUnreviewed) still wins when a row is focused.
- Updated help bar in `unified_review.html`: dropped stale `Y` / `1-7` / "Not Relevant" entries; surfaced `N/P` and `Shift+R`.
- Documented canonical shortcut mapping + single-letter vs chord policy in `.claude/rules/web.md`.

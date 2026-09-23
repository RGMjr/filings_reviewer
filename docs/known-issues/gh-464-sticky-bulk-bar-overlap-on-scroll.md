---
id: 464
source: gh
slug: sticky-bulk-bar-overlap-on-scroll
title: "Sticky review header and bulk-action-bar overlap each other on scroll (z-index 1010 vs 1011, same top)"
status: archived
severity: low
autonomy: skip
estimated: —
touches:
  - src/web/static/css/review.css
  - src/web/templates/unified_review.html
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 464
pr_refs:
  - 488
note: bulk-action-bar sticks at the same top as the sticky review header; overlaps visually when a thumbnail is selected and the page is scrolled
---

### Problem

On `/v2/review/<filing_id>` image tab, when the page is scrolled both `#bulk-action-bar` (`position: sticky; top: var(--navbar-height); z-index: 1011`) and `.review-sticky-header` (same `top`, `z-index: 1010`) stick simultaneously to the same vertical position. They visually overlap — the bulk-action-bar sits in front of the sticky filing header / tabs / filter bar, partially obscuring them whenever a thumbnail is checkbox-selected.

### Next Steps

- Either move `#bulk-action-bar` so its `top` is offset by the sticky-header's height (calc-based or via a JS-measured CSS variable), or
- Drop the sticky positioning on the bulk-action-bar and let it scroll with the sidebar

### Resolution

Fixed in PR #488. Added `--review-sticky-header-height: 130px` CSS variable to `:root` in `src/web/static/css/review.css`, then changed `#bulk-action-bar`'s `top` from `var(--navbar-height)` to `calc(var(--navbar-height) + var(--review-sticky-header-height))`. The bulk-action bar now stacks below the sticky review header (navbar + 130px offset) instead of overlapping it. Z-index values were not changed. The `130px` value accounts for the filing title row + tab bar + image filter bar + padding in the sticky header on the images tab; a comment in the CSS advises calibrating in DevTools if the header layout changes.

No Playwright stickiness assertion was added — the existing `tests/ui/review.spec.js` covers images-tab presence but has no scroll/sticky assertions. A scroll-based stickiness test would require a longer viewport scroll simulation; left as a follow-up.

---
id: 464
source: gh
slug: sticky-bulk-bar-overlap-on-scroll
title: "Sticky review header and bulk-action-bar overlap each other on scroll (z-index 1010 vs 1011, same top)"
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 464
note: bulk-action-bar sticks at the same top as the sticky review header; overlaps visually when a thumbnail is selected and the page is scrolled
---

### Problem

On `/v2/review/<filing_id>` image tab, when the page is scrolled both `#bulk-action-bar` (`position: sticky; top: var(--navbar-height); z-index: 1011`) and `.review-sticky-header` (same `top`, `z-index: 1010`) stick simultaneously to the same vertical position. They visually overlap — the bulk-action-bar sits in front of the sticky filing header / tabs / filter bar, partially obscuring them whenever a thumbnail is checkbox-selected.

### Next Steps

- Either move `#bulk-action-bar` so its `top` is offset by the sticky-header's height (calc-based or via a JS-measured CSS variable), or
- Drop the sticky positioning on the bulk-action-bar and let it scroll with the sidebar

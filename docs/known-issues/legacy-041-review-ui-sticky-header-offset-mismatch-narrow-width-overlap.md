---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 41
severity: n/a
slug: review-ui-sticky-header-offset-mismatch-narrow-width-overlap
source: legacy
status: archived
title: Review-UI Sticky Header Offset Mismatch + Narrow-Width Overlap
touches: []
updated: '2026-04-22'
---

`--navbar-height: 48px` CSS custom property unifies sticky offsets in `src/web/static/css/review.css`; `.review-pill-row` flex-wrap prevents narrow-width badge overlap. Deployed Render build verified visually. See commit `366d9dd`.

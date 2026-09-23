---
id: 562
source: gh
slug: demote-detection-tier-rollups
title: Demote Detection Tier rollups on /v2/review/stats Images tab
status: archived
severity: low
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-07
updated: 2026-05-08
gh_issue: 562
---

### Problem

The "Decisions by Detection Tier" and "Rejection Reasons by Detection Tier" cards on `/v2/review/stats` (Images tab) bucket reviewer decisions by image-shape confidence (`tier_1_cohort` / `tier_2_large` / `tier_3_all` / `presence_seed`). With the new "Image Decisions by Metric" card landing as the primary per-metric view, the tier rollups become more obviously niche — useful for relevance-model diagnostics but no longer the right top-of-tab signal for the keyword-rules team.

### Next Steps

- Move both tier cards into a collapsed `<details>` section labelled "Detection-tier diagnostics (relevance-model)" below the new per-metric card.
- Or gate them behind a dev-only flag if relevance-model work has fully shifted to a different surface.
- Either way, leave the queries (`db.get_image_decisions_by_tier_v2`, `db.get_image_rejection_reasons_by_tier_v2`) intact — only the template surface changes.

### Resolution

Both tier cards ("Decisions by Detection Tier" and "Rejection Reasons by Detection Tier") were wrapped in a collapsed `<details>` element with the summary label "Detection-tier diagnostics (relevance-model)" in `src/web/templates/unified_stats.html`. The cards appear below the "Image Decisions by Metric" card and are hidden by default; the underlying queries (`db.get_image_decisions_by_tier_v2`, `db.get_image_rejection_reasons_by_tier_v2`) remain intact. `.claude/rules/web.md` was updated to reflect the new collapsed placement.

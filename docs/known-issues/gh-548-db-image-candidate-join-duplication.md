---
id: 548
source: gh
slug: db-image-candidate-join-duplication
title: "db.py: get_images_with_decision_type duplicates JOIN structure from get_image_review_candidate_v2"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - src/infra/db.py
discovered: 2026-05-07
updated: 2026-05-07
gh_issue: 548
note: two DB helpers share the same complex JOIN aliases with no shared helper; silent drift risk if primary method evolves
---

### Problem

`get_images_with_decision_type` (added in the reviewer-badges / cross-filing decisions feature) duplicates the full `_V2_IMAGE_CANDIDATE_SELECT` JOIN structure (table aliases `v/f/c/d/imc_rollup/ic`) from `get_image_review_candidate_v2` with no shared abstraction. If the primary method gains new columns or renamed aliases, the cross-filing helper silently drifts and cross-filing pages show stale/missing data.

### Next Steps

- Evaluate whether a shared `_build_image_candidate_query` helper would reduce duplication without over-abstracting
- At minimum, add a comment in both methods cross-referencing the other so maintainers know to update both

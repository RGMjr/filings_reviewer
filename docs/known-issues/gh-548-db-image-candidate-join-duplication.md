---
id: 548
source: gh
slug: db-image-candidate-join-duplication
title: "db.py: get_images_with_decision_type duplicates JOIN structure from get_image_review_candidate_v2"
status: resolved
severity: low
autonomy: n/a
estimated: —
touches:
  - src/infra/db.py
discovered: 2026-05-07
updated: 2026-05-08
gh_issue: 548
pr_refs:
  - 549
  - 584
note: two DB helpers share the same complex JOIN aliases with no shared helper; silent drift risk if primary method evolves
---

### Problem

`get_images_with_decision_type` (added in the reviewer-badges / cross-filing decisions feature) duplicates the full `_V2_IMAGE_CANDIDATE_SELECT` JOIN structure (table aliases `v/f/c/d/imc_rollup/ic`) from `get_image_review_candidate_v2` with no shared abstraction. If the primary method gains new columns or renamed aliases, the cross-filing helper silently drifts and cross-filing pages show stale/missing data.

### Next Steps

- Evaluate whether a shared `_build_image_candidate_query` helper would reduce duplication without over-abstracting
- At minimum, add a comment in both methods cross-referencing the other so maintainers know to update both

### Resolution

PR #549 consolidated the `_V2_IMAGE_CONFIRMATION_ROLLUP_JOIN` fragment (the most complex part of the shared skeleton) into a single class attribute, eliminating that duplication.

The remaining FROM/JOIN skeleton shared by the three methods (`get_image_review_candidate_v2`, `get_image_review_candidates_for_filing_v2`, and `get_images_with_decision_type`) now has explicit cross-reference comments added directly above each method's SQL assignment, instructing maintainers to update all three in sync. No shared helper was introduced — the queries differ enough in WHERE clauses and projections that a single builder function would over-abstract.

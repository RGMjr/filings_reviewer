---
id: 540
source: gh
slug: forward-looking-rejection-category
title: Add forward_looking rejection category to Reject form
status: archived
severity: medium
autonomy: skip
estimated: —
touches:
  - src/review/models.py
  - src/web/routes/api_unified.py
  - src/web/text_decision_category_actions.py
  - sql/*.sql
discovered: 2026-05-07
updated: 2026-05-07
gh_issue: 540
note: Closed as not-planned 2026-05-07 (GH issue closed with reason `not planned`). Permanent rejection_category enum addition for a fuzzy benefit — no FP filter remediation, recommendation rule explicitly deferred, no data backfill, no quantified count of mis-bucketed rejections to act on. Reopen with (a) recent counts of `not_a_metric`/`other` rejections that should have been `forward_looking`, and (b) the FP filter or recommendation rule bundled in.
---

### Problem

Reviewers currently lack a dedicated category for analyst-target / guidance / projection numbers — these get mis-bucketed into `not_a_metric` (or `other`), conflating a distinct false-positive class with the broader "keyword too aggressive" signal. The Patterns-tab `not_a_metric` rollup is then noisier than it needs to be, and `compute_recommendations` can't surface a rule that targets forward-looking language specifically.

This was explicitly raised and deferred during the Reject-dropdown UX rework so the display-layer fix could ship first.

### Next Steps

- Add `forward_looking` to `REJECTION_CATEGORIES` (`src/review/models.py`) and `V2_REJECTION_CATEGORIES` (`src/web/routes/api_unified.py`).
- Timestamp migration in `sql/` widening the `rejection_category` CHECK constraint on `v2_review_decisions`.
- Add a `CATEGORY_ACTIONS` entry with reviewer-facing label/description/example and a `target_file` pointing at a forward-looking FP filter (likely `src/extraction_v2/stages/false_positive_filter.py` or a new rule).
- Optional: new `compute_recommendations` rule that fires when `rejection_categories['forward_looking'] / reject_count` clears a threshold.

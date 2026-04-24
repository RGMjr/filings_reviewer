---
autonomy: safe
discovered: '2026-04-24'
estimated: S
id: 101
severity: low
slug: get-image-review-candidate-v2-lacks-classification-join
source: legacy
status: open
title: get_image_review_candidate_v2 Missing Classification LATERAL Join
touches:
  - src/infra/db.py
  - src/web/routes/api_unified.py
updated: '2026-04-24'
---

### Problem

`DatabaseAdapter.get_image_review_candidate_v2` (single-image fetch used in
`api_unified.py` at lines ~335, ~423, ~478) does not include the LATERAL join
to `v2_image_classifications` added in Leg C. The function returns a dict
without `classification_id`, `predicted_metrics`, or `classification_confidence`.
Currently not a bug — the three callers don't surface classification data — but
is a latent gap if any future caller or API endpoint needs Vision output from
the single-image path.

### Next Steps

- Apply the same `LEFT JOIN LATERAL (...) ic ON true` pattern from
  `get_image_review_candidates_for_filing_v2` to `get_image_review_candidate_v2`.
- Add the three columns (`ic.classification_id`, `ic.predicted_metrics`,
  `ic.confidence AS classification_confidence`) to the single-image SELECT.
- Verify API endpoints at `api_unified.py:335`, `:423`, `:478` still pass
  their existing tests after the change.

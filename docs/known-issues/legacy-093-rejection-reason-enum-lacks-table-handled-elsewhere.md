---
autonomy: n/a
discovered: '2026-04-23'
estimated: S
id: 93
severity: low
slug: rejection-reason-enum-lacks-table-handled-elsewhere
source: legacy
status: open
title: v2_image_review_decisions.rejection_reason Enum Lacks "table_handled_elsewhere"
touches:
  - sql/29_v2_image_review_decisions.sql
  - src/gold_standard/image_eval.py
  - scripts/benchmark_vision.py
updated: '2026-04-23'
---

### Problem

When the metric-classify harness (PR B5.x.1) sees a table-in-image it
returns `predicted_metrics=[]` + `rejection_reason="other"` because the
existing enum on `v2_image_review_decisions.rejection_reason`
(migration 29: `decorative`, `not_a_chart`, `wrong_subject`,
`duplicate`, `unreadable`, `other`) has no "table" bucket. The detail
is carried in the `reasoning` free-text field, but the bucketing is
blurry — `"other"` mixes genuine unknowns with routed-elsewhere
tables, which hurts downstream analytics.

Tables are handled by the separate full-page-OCR pipeline
(`VisionClient.analyze_image_for_text`, PRs #110 / #114 / #139), so a
dedicated enum value would let reviewers + analytics distinguish
"classifier chose not to classify — route elsewhere" from "classifier
genuinely unsure".

### Next Steps

- Add a migration extending the enum:
  `ALTER TYPE rejection_reason ADD VALUE 'table_handled_elsewhere';`
  (or the Postgres check-constraint form, depending on how the enum
  is modelled — check `sql/29_v2_image_review_decisions.sql`).
- Update `REJECTION_REASONS` in `src/gold_standard/image_eval.py` and
  `CLASSIFY_REJECTION_REASONS` in `scripts/benchmark_vision.py` to
  include the new value.
- Update the review UI surface so reviewers can pick the value
  manually (and so the classifier's emission maps cleanly).
- Back-fill any existing `"other"` rows whose `reasoning` references
  a table — optional, tracked separately if useful.

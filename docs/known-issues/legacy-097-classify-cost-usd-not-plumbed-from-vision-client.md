---
autonomy: safe
discovered: '2026-04-23'
estimated: S
id: 97
severity: low
slug: classify-cost-usd-not-plumbed-from-vision-client
source: legacy
status: open
title: v2_image_classifications.cost_usd Persists as 0 — VisionClient Helper Doesn't Surface Cost
touches:
  - src/llm/vision_client.py
  - src/extraction_v2/stages/image_classify.py
updated: '2026-04-23'
---

### Problem

`VisionClient.analyze_image_for_metric_classification` returns only the
parsed classification dict (`predicted_metrics`, `confidence`,
`rejection_reason`, `reasoning`) — it does not surface `cost_usd` or
any provider metadata from the underlying `analyze_image()` response.
As a result, `v2_image_classifications.cost_usd` always persists as
0.0, and the cost spot-check SQL in
`docs/operations/metric-classify-pipeline.md` cannot give real budget
signal once the gate is flipped. Latency is captured correctly
(wall-clock in `_classify_one`); only cost is missing.

### Next Steps

- Extend the helper's return shape to include `_cost_usd` (or a
  `metadata` sub-dict) pulled from the `VisionResponse.cost_usd`
  attribute of the underlying `self.analyze_image(...)` call.
- Update `ImageClassifyStage._classify_one` to read the new field
  (the line currently does `parsed.pop("_cost_usd", 0.0)` in
  anticipation).
- Backfill: the first few classify-enabled runs will have cost=0 in
  the table. Leave as-is; the plumbing fix applies forward.

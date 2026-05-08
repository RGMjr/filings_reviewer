---
autonomy: n/a
discovered: '2026-05-08'
estimated: S
gh_issue: 577
id: 577
severity: medium
slug: eval-threshold-sweep-score-mismatch
source: gh
status: resolved
title: evaluate_vision_metric_scores threshold sweep contradicts DB score distribution
touches:
  - scripts/evaluate_vision_metric_scores.py
updated: '2026-05-08'
---

### Problem

`scripts/evaluate_vision_metric_scores.py` produced a report with 124 (img_id, metric_id) pairs where the threshold-sweep `Predicted+` column was constant at 8 across thresholds 0.1–0.9. That implies all 8 positives have score ≥0.9 and all 116 negatives have score <0.1.

But a direct query against `v2_image_classifications.predicted_metrics` (after the May 8 backfill via `scripts/backfill_image_classifications.py`) shows zero predictions with score below 0.5:

```
0.5-0.9    98
0.9-1.0    17
1.0        19
```

The eval's pair list is built from these same predictions joined to `build_label_map`, so the score distribution in pairs should match the DB. It doesn't.

### Why it matters

The Phase 2 plan (`~/.claude/plans/we-have-processed-a-cryptic-pelican.md`) uses this eval's AUC and threshold sweep to decide whether Phase 2b (a runtime filter on `v2_image_classifications.predicted_metrics` confidence) is safe to ship. A spurious AUC=1.0 driven by a threshold-sweep bug would green-light a filter whose real-world precision/recall trade-off is unknown.

### Likely root cause (hypothesis, not confirmed)

Three candidates, in rough order of likelihood:

1. **Score-column read issue.** `(elem->>'score')::float` might silently return 0.0 for rows where the JSON value is NULL or non-numeric. If a sizable subset of `predicted_metrics` entries have `score: null` or are missing the field entirely, those would all collapse to 0.0 and look like a "<0.1" cluster.
2. **`latest_classifications` CTE interaction.** `DISTINCT ON (img_id) ORDER BY created_at DESC` selects one row per image. The post-filter `WHERE jsonb_array_length(lc.predicted_metrics) > 0` drops images where the latest is empty — but if multiple classification runs exist for an image, the eval might be reading scores from a stale earlier run that the DB-distribution query also covers but in different counts.
3. **Sentinel-expansion side effect.** `build_label_map` adds sentinel-reject negatives keyed on `(img_id, metric_id)` for ALL Vision-predicted metrics on that image. The `pairs` builder then joins back to `predictions` for the score. If the join logic accidentally matches a different prediction row (e.g. wrong key order) the score could come from somewhere unexpected.

### Reproduction

```bash
python3 scripts/evaluate_vision_metric_scores.py --output /tmp/eval.txt
cat /tmp/eval.txt
```

Compare `Predicted+` column against:

```sql
SELECT
    CASE WHEN (elem->>'score')::float < 0.1 THEN '0.0-0.1'
         WHEN (elem->>'score')::float < 0.5 THEN '0.1-0.5'
         WHEN (elem->>'score')::float < 0.9 THEN '0.5-0.9'
         WHEN (elem->>'score')::float < 1.0 THEN '0.9-1.0'
         ELSE '1.0' END AS bucket,
    COUNT(*)
FROM v2_image_classifications vic, jsonb_array_elements(vic.predicted_metrics) AS elem
GROUP BY 1 ORDER BY 1;
```

### Suggested fix shape

1. Add a debug print or assertion in `run()` (`scripts/evaluate_vision_metric_scores.py`) that logs the score histogram of `pairs` immediately before `generate_report` is called.
2. Compare to the DB-distribution query.
3. Fix whichever of the three causes above is responsible.
4. Add a unit test that seeds a small `v2_image_classifications` corpus with known scores and asserts the threshold sweep reproduces the seeded distribution.

### Out of scope

- Whether Vision per-metric scores are calibrated enough to filter on (that's the Phase 2b decision).
- Sentinel-reject label semantics (separate question of whether expansion is appropriate).

### Resolution

None of the three hypotheses in this fragment was the actual cause. The bug was a list-comprehension destructuring error in `generate_report` (`scripts/evaluate_vision_metric_scores.py`):

```python
y_true = [label for _, _, _, label in pairs]
y_score = [score for _, _, _, score in pairs]   # bug: extracts pos 4 (label), not pos 3 (score)
```

Both list comprehensions extract the same tuple position (the 4th, the label) — the variable name (`score` vs `label`) does not affect what gets bound. As a result `y_score` was actually the label list, and the threshold sweep collapsed to "Predicted+ = count of positives" at every threshold, with AUC and AP both spuriously 1.0.

Fix: use index-based extraction so the column position is unambiguous:

```python
y_true = [p[3] for p in pairs]
y_score = [p[2] for p in pairs]
```

Re-running the eval after the fix produces the expected varying threshold sweep that matches the DB score distribution (e.g. 382 Predicted+ at thresh=0.5, dropping to 75 at thresh=0.9). Regression coverage added in `tests/integration/test_evaluate_vision_metric_scores.py::TestThresholdSweep`: `test_sweep_uses_score_not_label` would return Predicted+ = 3 at every threshold under the bug; `test_auc_reflects_score_distribution` would return AUC=1.0 under the bug.

---
id: 478
source: gh
slug: predicted-relevance-not-persisted
title: v2_image_assets persistence INSERT omits predicted_relevance — gate runs in-memory but score never reaches DB
status: archived
severity: high
autonomy: review
estimated: S
touches:
  - src/extraction_v2/persistence.py
  - tests/integration/extraction_v2/test_persistence_detected_metrics.py
  - tests/unit/extraction_v2/test_persistence_sql.py
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 478
note: zero of 2,395 prod image rows have predicted_relevance set; INSERT at persistence.py:899 lacks the column entirely; gh-442 gating effect is real but score is silently dropped at DB write
---

### Problem

`src/extraction_v2/persistence.py:899` is the canonical INSERT for `v2_image_assets`. Its column list and `ON CONFLICT (filing_id, filename) DO UPDATE SET` clause both omit `predicted_relevance`. The image_triage stage at `src/extraction_v2/stages/image_triage.py:660` sets `asset.predicted_relevance = score` in memory, but persistence drops that field.

The score is only ever written by an offline script: `scripts/score_image_candidates.py:152` runs `SET predicted_relevance = %(score)s` keyed on `img_id`. That script is not part of the extraction pipeline and is not invoked in prod.

### Empirical proof

```sql
SELECT COUNT(*), COUNT(predicted_relevance) FROM v2_image_assets;
-- total=2395  scored=0
```

Zero of 2,395 prod image rows have `predicted_relevance` populated. Ever — across every retrain, every gh-442 flip, every Render redeploy.

### Why the gh-442 gating effect is still real

`USE_LEARNED_TRIAGE=true` causes `image_triage` to filter the in-memory asset list — sub-threshold images are removed before downstream OCR/Vision stages run. That filtering effect IS happening (when the gh-477 module-level env-var trap is also handled). What's NOT happening is persisting the score:

- The in-memory gate fires correctly per filing.
- Downstream cost (OCR/Vision API calls) is correctly avoided for sub-threshold images.
- The DB `predicted_relevance` column is always NULL, which means:
  - The model-score sort UI (#407) cannot rely on the column; the route handler's score-on-render code path (which I shipped as a fallback) is the only thing actually working.
  - Analysis scripts that bucket by `predicted_relevance` get nothing.
  - PR #462's verification SQL (`COUNT(*) WHERE predicted_relevance IS NOT NULL > 0`) is a no-op success metric — it can never trigger.

### Discovery

Found while investigating filing 1529 (2026-05-04 ingest test). After confirming env vars on `filings-onboarding-runner` were correct (`USE_LEARNED_TRIAGE=true`, `LEARNED_TRIAGE_MIN=0.32`, `GOOGLE_API_KEY` set, worker manually redeployed), filing 1529's single chart image still had `predicted_relevance = NULL`. Tracing through `persistence.py:899` confirmed the column is absent from the INSERT.

### Next Steps

1. Add `predicted_relevance` to the INSERT column list, VALUES clause, and `ON CONFLICT DO UPDATE SET` clause at `persistence.py:899`. Three small additions, one file.
2. Unit test: insert an asset with `predicted_relevance=0.65`, fetch the row, confirm the column is set. Use the existing `tests/integration/extraction_v2/test_persistence*.py` fixtures.
3. Backfill decision: 2,395 prod rows have NULL `predicted_relevance`. After the fix, `scripts/score_image_candidates.py` can backfill — it operates on `img_id` independent of the extraction pipeline. Recommend backfill (cheap: no R2 fetches, ~21 features per row through cached sklearn pipeline).
4. Update gh-442's verification claim: the `COUNT(*) WHERE predicted_relevance IS NOT NULL > 0` check should actually fire on a fresh extraction post-fix.

### Related

- gh-477 (module-level env-var trap in `image_triage.py`) is a separate bug. Both real, both need fixing. gh-477 affects whether the gate fires; this affects whether the score is persisted. Even with gh-477 fixed, this bug would keep `predicted_relevance` NULL.
- gh-441 (metric-classify gate) was confirmed live empirically in this same investigation — `v2_image_classifications` produced rows from prod after `GOOGLE_API_KEY` got set. So the metric-classify persistence path is fine; only `v2_image_assets.predicted_relevance` is broken.

### Verification

- Apply the fix; run a small ingest (1–2 filings); confirm:
  ```sql
  SELECT COUNT(predicted_relevance) FROM v2_image_assets WHERE filing_id = <new_id>;
  ```
  Returns > 0 with values in [0,1].
- Optionally re-run `scripts/score_image_candidates.py` to backfill historical NULL rows; confirm via the same SQL on existing filing IDs.
- Verify the model-score sort UI now shows score badges sourced from the DB column (not just from score-on-render). The route can be left with the score-on-render path as defensive belt-and-suspenders, or simplified to read the column.

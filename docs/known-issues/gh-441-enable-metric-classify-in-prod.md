---
id: 441
source: gh
slug: enable-metric-classify-in-prod
title: Enable Vision-API metric classifier in prod (ENABLE_METRIC_CLASSIFY=true)
status: archived
severity: medium
autonomy: review
estimated: S
touches:
  - render.yaml
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 441
pr_refs:
  - 444
note: ENABLE_METRIC_CLASSIFY=true enabled in prod via PR #444; v2_image_classifications now populated by the filings-extraction cron with Gemini Flash Lite predictions.
---

### Problem

`v2_image_classifications` is empty in prod. The Vision-API metric classifier (Tripod Leg B from #92) is fully wired in `src/extraction_v2/stages/image_classify.py` and the bake-off model (`gemini-2.5-flash-lite`) is the confirmed default — but the gate in `render.yaml:63` (`filings-extraction` cron) is set to `"false"` with the comment "Flip to 'true' after smoke-test."

The "smoke-test" deferral has outlasted its original premise. Cost is the cheapest Gemini Flash Lite tier (per 2026-04-23 bake-off), errors are caught and non-fatal (the stage doesn't block other pipeline stages on failure), and the data is needed to build downstream reviewer surfaces (per-metric prediction confidence in the image card UI, training data for any future ID classifier work).

### Next Steps

1. Brief local smoke test: run `scripts/batch_v2_extraction.py` on ~3 filings with `ENABLE_METRIC_CLASSIFY=true` locally (against `TEST_DATABASE_URL`). Verify rows land in `v2_image_classifications` with non-NULL `predicted_metrics` and `confidence` populated.
2. Flip `render.yaml:63` value to `"true"` (just the value, not the comment — preserve the historical pointer to #92 for context).
3. Monitor first nightly batch: row count growth in `v2_image_classifications`, no error spike in `filings-extraction` worker logs.
4. Decide whether `VISION_CLASSIFY_THRESHOLD=0.5` warrants tuning before flip — note from `.claude/rules/infrastructure.md` env table: "Records below the floor are still persisted with their true confidence." The threshold only affects the downstream `predicted_relevant` projection, not the row write. Default 0.5 is fine for the initial flip.

### Verification

- A new nightly batch produces rows in `v2_image_classifications` for chart and table_image assets.
- `confidence` distribution looks reasonable (not all 0.0, not all 1.0).
- `predicted_metrics` references valid metric IDs from `v2_metric_definitions`.
- No spike in `filings-extraction` worker error logs.
- Per-filing extraction runtime increase is bounded (one Gemini Flash Lite call per chart/table image; for a typical 10-chart filing, ~3-5s added).

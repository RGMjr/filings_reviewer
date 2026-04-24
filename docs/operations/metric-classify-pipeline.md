# Metric-Classify Pipeline Runbook

Vision-API metric-classify stage — Leg B of the metric-classify tripod
(closes known-issue #92 and #93).

## What it does

For each chart / table_image on a filing, the pipeline calls
`VisionClient.analyze_image_for_metric_classification(image_bytes)` and
persists the output (`predicted_metrics`, `confidence`, `rejection_reason`,
`reasoning`, provider/model metadata, cost/latency) to
`v2_image_classifications`.

Relationship to adjacent data:

- `v2_image_assets.detected_metrics` (JSONB) — rule-based keyword match,
  written once per extraction by `ChartFactBridgeStage`. Stays untouched.
- `v2_image_metric_confirmations` — reviewer accept/reject/correct/add
  decisions on whichever predictions were shown. Untouched here; wired up
  in Leg C.
- `v2_image_classifications` — the Vision-API audit trail. Append-only;
  multiple rows per `img_id` OK (re-runs keep history).

## How to enable

Default off. Flip by setting on the `filings-extraction` cron service in
Render:

| Var | Default | Flip to |
|---|---|---|
| `ENABLE_METRIC_CLASSIFY` | `false` | `true` |
| `VISION_CLASSIFY_PROVIDER` | `gemini` | keep |
| `VISION_CLASSIFY_MODEL` | `gemini-2.5-flash-lite` | keep (bake-off winner) |
| `VISION_CLASSIFY_THRESHOLD` | `0.5` | keep |
| `GEMINI_API_KEY` | unset | **must be set manually in Render** |

Local testing:

```bash
DATABASE_URL="$TEST_DATABASE_URL" \
ENABLE_METRIC_CLASSIFY=true \
python3 scripts/batch_v2_extraction.py --filing-ids 123 --workers 1 --limit 1
```

## Verification after turning on

```sql
-- Is it firing at all?
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT img_id) AS distinct_images,
       MIN(created_at) AS first_row,
       MAX(created_at) AS last_row
  FROM v2_image_classifications
 WHERE created_at > NOW() - INTERVAL '24 hours';

-- Cost + latency sanity
SELECT provider,
       model,
       COUNT(*)                      AS rows,
       ROUND(SUM(cost_usd)::numeric, 4)  AS total_usd,
       ROUND(AVG(latency_ms)::numeric)   AS avg_latency_ms
  FROM v2_image_classifications
 WHERE created_at > NOW() - INTERVAL '24 hours'
 GROUP BY provider, model;

-- Rejection-reason distribution
SELECT rejection_reason, COUNT(*)
  FROM v2_image_classifications
 WHERE created_at > NOW() - INTERVAL '24 hours'
 GROUP BY 1
 ORDER BY 2 DESC;
```

## Re-running one filing

There is no guard against re-classification — the table is append-only,
so calling `persist_pipeline_result` again adds rows rather than
overwriting. Use `DISTINCT ON (img_id) ORDER BY created_at DESC` in
downstream reads to pick the latest per image.

If you want to remove stale classifications for a filing:

```sql
DELETE FROM v2_image_classifications
 WHERE img_id IN (
       SELECT img_id FROM v2_image_assets WHERE doc_id = :filing_id
 );
```

## Cost envelope

Per the 2026-04-23 bake-off on `gemini-2.5-flash-lite`:

- **Cost:** ~$0.00218 per image
- **Latency:** ~1,590 ms per image
- **Rough daily cap:** 300 images × 100 filings/day ≈ $65/day

If spot-checks show higher burn than expected:

1. Confirm classify only runs for `{chart, table_image}` — decorative /
   logo / signature must NOT be classified (see
   `ImageClassifyStage._CLASSIFIABLE_IMAGE_TYPES`).
2. Consider a per-filing image-count cap as a follow-up (out of scope
   for Leg B).

## Known follow-ups

- **Cost propagation** — `VisionClient.analyze_image_for_metric_classification`
  does not currently surface `cost_usd` in its return dict, so
  `v2_image_classifications.cost_usd` is persisted as 0 until this is
  plumbed. Track as a follow-up KI.
- **Leg C (review-UI)** — shipped. See "Reviewer UI" section below.

## Reviewer UI

The Images tab in the review UI surfaces classifier predictions alongside the
existing rule-based signal. **Source priority:** `v2_image_classifications.predicted_metrics`
(Vision) is shown when a classification row exists for the image; the card
falls back to `v2_image_assets.detected_metrics` (Keywords) when it does not.

The card header label indicates which source is active:

- **"Predicted metrics (Vision)"** — classifier output from `v2_image_classifications`
- **"Detected metrics (Keywords)"** — rule-based output from `v2_image_assets`

Reviewer decisions (accept / reject / correct / add) are recorded in
`v2_image_metric_confirmations` regardless of which source powers the card.
The confirmation endpoint (`POST /api/v2/image-metric-confirmations`) is
unchanged — both sources produce `{metric_id, score}` shaped entries.

The `data-classification-id` attribute on the card div carries the
`v2_image_classifications.classification_id` of the row that supplied the
predictions (empty string when falling back to rule-based), for future
training-signal queries.

**While `ENABLE_METRIC_CLASSIFY=false` (current prod default):** no
classification rows exist, so every image shows the Keywords card. Behavior
is identical to pre-Leg-C. The Vision path activates automatically once the
gate is flipped.

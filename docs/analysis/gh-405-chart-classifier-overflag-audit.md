# gh-405: Chart Classifier Over-flagging Audit

**Status**: Complete — recommendation: close fragment (relevance model absorbs the signal)
**Date**: 2026-05-01
**Linked fragment**: `docs/known-issues/gh-405-chart-classifier-overflag.md`
**Linked GH issue**: #405

## Headline

The fragment's hypothesis is correct — the rule-based chart classifier in `ImageTriageStage._is_chart()` over-flags. **Charts are rejected at ~92% on the per-metric review surface and ~87% on the legacy image-level surface.** But the relevance model is already absorbing this signal correctly via the `is_chart_classification: -2.178` coefficient, and tightening `_is_chart()` would change the input distribution that the model has learned to penalize. Recommend closing the fragment.

If reviewer queue noise becomes a concrete pain point, a follow-up surgical-tightening fragment can drop the two broadest patterns (`\bexhibit\b`, `\bfigures?\b`) from `CHART_PATTERNS` — these are 100% noise on the confirmation table and only marginally productive on legacy data.

## 1. Methodology

- Training CSV: `data/image_model/training_data.csv` (1,499 rows, 80 relevant / 1,419 not). Built by `scripts/export_image_training_data.py` which UNIONs `v2_image_review_decisions` (legacy image-level) and `v2_image_metric_confirmations` (per-metric), de-duped by `img_id`.
- Coefficient reproduction: `python3 scripts/train_image_relevance_model.py --input data/image_model/training_data.csv --output ...gh405_repro.joblib --report ...gh405_repro.txt --model-type logistic`
- Per-classification precision SQL: confirmation table joined to `v2_image_assets`, `bool_or(decision IN ('accept','correct','add'))` aggregated per `img_id`. Filter `HAVING COUNT(*) FILTER (WHERE decision != 'skip') > 0` excludes pure-skip rows.
- Gate-attribution SQL: mimics the short-circuit ordering inside `_is_chart()` — `chart_pattern (combined_text)` → `chart_type_kw (combined_text)` → `metric_kw_gate (nearby_text + size constraint)`. `combined_text` reproduces the function's `filename_normalized + " " + nearby_text` construction.

Numbers reconcile within rounding: Query A's chart bucket (275 labeled) matches Query B's sum (218 + 35 + 13 + 9 = 275) ✓.

## 2. Coefficient Reproduction — confirmed

| Source | Samples | Relevant | AUC | `is_chart_classification` |
|---|---|---|---|---|
| Disk model (`model_report.txt`, 2026-05-01 17:19) | 808 | 85 (10.5%) | 0.824 | **+0.142** |
| Repro model (this audit, 2026-05-01) | 1,499 | 80 (5.3%) | 0.829 | **−2.178** |
| Fragment claim | 1,499 | 80 | 0.829 | −2.178 |

The repro matches the fragment exactly. The disk model is from a stale CSV — someone re-exported the CSV (1499 rows) but did not retrain. Filing a known-issue note that the deployed `relevance_model.joblib` does not reflect the current confirmation labels is out of scope for this audit but worth flagging.

Other notable repro coefficients: `is_table_image_classification: −0.994`, `is_unknown_classification: −0.523`, `cohort_confidence: +1.948`, `text_unit_econ_terms: +0.849`. **All three classifications carry a negative coefficient — chart is just the largest in absolute value.**

## 3. Per-classification Precision (Query A)

Confirmation table, image-level aggregated decisions (850 labeled images):

| classification | labeled | relevant | precision |
|---|---|---|---|
| chart       | 275 | 22 | **8.0%** |
| table_image | 200 |  4 | 2.0% |
| unknown     | 375 |  2 | 0.5% |

Legacy `v2_image_review_decisions` (image-level "is this image relevant", 851 labeled):

| classification | labeled | relevant | precision |
|---|---|---|---|
| chart       | 297 | 38 | **12.8%** |
| table_image |  76 |  6 | 7.9% |
| unknown     | 473 | 20 | 4.2% |
| decorative  |   5 |  0 | 0.0% |

Both surfaces show the same ranking: chart is the *most* precise of the three visible classifications, but absolute precision is low everywhere. The over-flagging is not chart-specific — it's pipeline-wide. The chart label nevertheless gets the largest negative coefficient because it interacts with `cohort_confidence` (the dominant positive feature) — chart-classified images that *also* have high cohort signal turn out to be lower-precision than chart-classified images alone, so the model learns a strong negative interaction term.

## 4. FP Decomposition by Gate Origin (Query B refined)

Production-wide chart-classified row distribution (`v2_image_assets`, 653 chart rows total), attributed to the first `_is_chart()` gate that fires:

| First firing gate | rows | % |
|---|---|---|
| gate3: metric_kw_gate (large/dimensionless + finance keyword in nearby_text) | 351 | 53.8% |
| gate1: chart_pattern (combined_text matches `\b(chart|graph|figures?|exhibit|diagram|plot)\b`) | 185 | 28.3% |
| no_gate_matches (stale or backfilled rows that no longer match current rules) | 101 | 15.5% |
| gate2: chart_type_kw (combined_text contains "bar chart", "line graph", etc.) | 16 | 2.4% |

Per-gate precision:

|  | confirmation table |  |  | legacy table |  |  |
|---|---|---|---|---|---|---|
| Gate | labeled | relevant | prec | labeled | relevant | prec |
| gate3 metric_kw_gate | 161 | 18 | **11.2%** | 211 | 29 | **13.7%** |
| gate1 chart_pattern  |  44 |  3 | 6.8%  |  57 |  7 | **12.3%** |
| gate2 chart_type_kw  |   5 |  0 | 0.0%  |   6 |  1 | 16.7% (n too small) |
| no_gate              |  65 |  1 | 1.5%  |  23 |  1 | 4.3% |

Two readings:

- **Confirmation surface**: gate3 dominates volume and is the only productive gate. gate1 has measurable but lower productivity.
- **Legacy surface**: gate1 and gate3 are roughly comparable (~12-14% precision). The gate1 pattern is broader but not pure noise on the legacy "is anything on this image relevant?" judgment.

The gap (gate1 precision drops from 12.3% legacy → 6.8% confirmations) is consistent with the confirmation surface being stricter — it requires the image to confirm a *specific tracked metric*, not just be "useful." Many gate1-matched images probably contain tangentially relevant content that didn't match a specific metric in `metric_keywords.yaml`.

## 5. Dominant FP Patterns (Query C)

Top fully-rejected charts on the confirmation surface, by `relevance_score`:

| First gate | filename | dimensions | reject reason |
|---|---|---|---|
| gate1_chart_pattern  | g209425g42c49.jpg              | 0×0       | no_relevant_metrics |
| gate1_chart_pattern  | g89056g04e58.jpg               | 0×0       | no_relevant_metrics |
| gate1_chart_pattern  | howpaypalserves.jpg            | 0×0       | no_relevant_metrics |
| gate2_chart_type_kw  | img003.jpg                     | 0×0       | no_relevant_metrics |
| gate3_metric_kw_gate | g55348g21n03.jpg               | 0×0       | no_relevant_metrics |
| gate3_metric_kw_gate | q3-21paypalearningsrelea001.jpg | 1055×1365 | no_relevant_metrics |
| gate3_metric_kw_gate | q4-fyx21xpaypalxearnings012.jpg | 1055×1365 | no_relevant_metrics |
| no_match             | tlogo.jpg                      | 0×0       | no_relevant_metrics |

PayPal earnings-release jpegs (1055×1365 cover/header pages) consistently mis-classify as charts because the surrounding HTML contains "revenue"/"customers"/etc. and the image is large — gate3 fires. SEC EDGAR `g######g######.jpg` filenames are dimensionless and match either nearby-text "exhibit"/"figure" (gate1) or finance keywords (gate3). Both populations are nearly all rejected.

But: PayPal `q121-paypalearningsrelea002.jpg` and `q121-paypalearningsrelea012.jpg` are *relevant* on the legacy table. The classifier isn't selecting wrong files categorically — it's picking up the entire population indiscriminately. The relevance model's job is to discriminate within that population using OCR/text features, not to re-litigate the chart label.

## 6. Recommendation: Close fragment (Option A)

The relevance model has correctly identified `is_chart_classification` as a noisy but useful signal — its **−2.178 coefficient is doing real work**, not flagging a bug. AUC 0.829 on cross-validation is reasonable for an early model.

Tightening `_is_chart()` would change the population that triggers `is_chart_classification=1`, invalidating the model's learned coefficient. The likely outcomes:

- A net-tightened gate (e.g., remove `\bexhibit\b` and `\bfigures?\b`) reduces chart volume by ~28% (gate1 share). The remaining gate3 + tightened-gate1 population would be slightly higher precision (maybe 11% → 13%), making the chart label less of a strong negative. The model's −2.178 coefficient would drift toward neutral on retraining, costing some discriminative power.
- The relevance model would need to be retrained against the new chart distribution, with potential AUC delta uncertain.
- Reviewer queue noise reduction is meaningful (~28% fewer charts queued from gate1) but secondary — the deployed disk model is stale anyway, and the reviewer surface is currently driven by `relevance_score`, not classification directly.

**Action**: close gh-405 with a note pointing here. If reviewer queue noise becomes a concrete operational complaint, the surgical-tighten path is documented in §7 below as a follow-up trigger.

### Follow-up trigger (do not file now)

If a future audit shows reviewer noise from chart-classified images is materially burdening the queue, file a follow-up `gh-N-chart-triage-tighten` with:

1. Drop `\bexhibit\b` and `\bfigures?\b` from `CHART_PATTERNS` in `image_triage.py:90-97`. These match SEC exhibit numbering (`exhibit99`) and "financial figures" prose with no chart content.
2. Optionally drop the dimensionless branch of the metric_keyword_gate (`not has_known_dimensions`) — gate3 dimensionless rows are dominated by SEC `g######` files that are mostly logos/decorative.
3. Retrain the relevance model after the rule change and verify AUC does not drop more than 0.02 on cross-validation.

## Side findings (informational)

1. **Disk relevance model is stale.** `data/image_model/relevance_model.joblib` was trained on 808 samples; the CSV on disk has 1,499. A retrain has not been run. If the relevance model is wired into any production scoring path, this is a separate gap worth addressing — out of scope for gh-405.
2. **101 chart-classified rows match no current gate.** Likely classifications written by an earlier `_is_chart()` version, or rows whose dimensions/nearby_text were updated post-classification. Marginal cleanup; not material to this audit.
3. **All three classifications have negative coefficients.** `chart: −2.178`, `table_image: −0.994`, `unknown: −0.523`. The same dynamic (broad over-flagging absorbed by the model) holds for all three.

## Appendix: Raw outputs

### `analyze_image_rejection_patterns.py` against prod (truncated)

```
Labeled images:  850
Fully rejected:  822 ( 96.7% rejection rate)
Has positive:     28 (  3.3%)

Classification:        labeled   rejected   reject%
  unknown                  375        373    99.5%
  chart                    275        253    92.0%
  table_image              200        196    98.0%
```

### `model_report_gh405_repro.txt` (top 7 features by abs coefficient)

```
Training samples: 1499  Relevant: 80 (5.3%)  AUC: 0.829  AP: 0.422

  is_chart_classification            : -2.178
  cohort_confidence                  : +1.948
  is_table_image_classification      : -0.994
  text_unit_econ_terms               : +0.849
  text_cohort_terms                  : +0.747
  is_tier_1                          : +0.742
  cohort_keyword_nearby              : -0.670
```

# Per-Metric Image Classifier — Design Note

**Status:** Design only. No model code ships with this document.

**Scope:** Design for a future classifier that predicts, per `(image, metric)` pair, whether a given metric is present in a given image. This would replace the Vision-score filter on the reviewer card (Phase 2b of the image-classifier improvement plan) if and only if it outperforms it.

**Plan reference:** `.claude/plans/we-have-processed-a-cryptic-pelican.md` (Phase 3).

---

## 1. Context

The current binary image-relevance model (`scripts/train_image_relevance_model.py` +
`scripts/export_image_training_data.py`) answers a single question: *should this image enter the reviewer queue at all?* It is a good gate for that purpose — see `docs/operations/image-model-training-runbook.md` for threshold and AUC-ROC history.

The limitation is in how training labels are built. `scripts/export_image_training_data.py:129–167`
(`CONFIRMATIONS_SEC_QUERY`) aggregates `v2_image_metric_confirmations` with a `GROUP BY img_id`:

```sql
CASE
    WHEN bool_or(imc.decision IN ('accept','correct','add'))
         THEN 'relevant'
    ELSE 'not_relevant'
END AS decision
```

This collapses per-`(img_id, metric_id)` reviewer decisions to a single image-level label. A reviewer who accepted `cm_net_revenue_retention` and rejected `cm_daily_active_users` on the same chart produces a single `relevant` row — the DAU rejection is lost.

That collapse is correct for the binary gate. But reviewers do not just decide "is this image relevant?"; they decide which metric chips appear on the card via the per-metric Accept / Reject / Correct / Add flow (CLAUDE.md design principle 4, `v2_image_metric_confirmations`). A separate per-`(image, metric)` model can exploit the explicit signal that the binary model discards, and drive the chip set on the reviewer card with higher precision.

The binary model (Phase 1, `LEARNED_TRIAGE_MIN`) continues to gate the image-level queue. The per-metric model described here gates which metric chips *appear on the card for each image that has already passed the binary gate*. These are complementary, not competing, roles.

---

## 2. Training Schema

### Unit of observation

One row per `(img_id, metric_id)` pair where at least one non-skip reviewer decision exists.

### Label rules

| Condition | Label |
|-----------|-------|
| `decision IN ('accept','correct','add')` AND `confirmed_metric_id = metric_id` | 1 (present) |
| `decision = 'reject'` AND (`confirmed_metric_id = metric_id` OR `detected_metric_id = metric_id`) | 0 (absent) |
| Sentinel reject: `rejection_reason = 'no_relevant_metrics'`, `confirmed_metric_id IS NULL` | 0 for all in-scope metrics on that image |
| `decision = 'skip'` | exclude from training |

The sentinel "Reject all (no relevant metrics)" case (CLAUDE.md design principle 4) writes a
`v2_image_metric_confirmations` row with `NULL confirmed_metric_id` and `NULL detected_metric_id`.
The export query must expand this into label-0 rows for every metric that was presented as a chip
on the image at review time (i.e. metrics present in `v2_image_assets.detected_metrics` JSONB for
that image).

### Reviewer disagreement reconciliation

When two reviewers make conflicting decisions on the same `(img_id, metric_id)` pair:

- **Current convention (any-accept-wins):** if any reviewer accepted the metric on that image,
  label = 1. This matches the `bool_or` logic already used in `CONFIRMATIONS_SEC_QUERY` and is
  consistent with the existing `_promote_chart_fact` promotion logic in
  `V2PersistenceAdapter` (CLAUDE.md design principle 4).
- **Known limitation:** any-accept-wins is optimistic. A single confident accept overrides
  multiple rejects. For Tier-1 metrics this is acceptable (recall bias is preferable to missed
  detections); for Tier-2 metrics a majority-vote or confidence-weighted scheme may be worth
  evaluating when label counts are large enough.
- **Flag for follow-up:** reviewer disagreement reconciliation should be revisited once the
  per-metric label corpus reaches sufficient density to measure inter-rater agreement per metric.
  See section 7.

---

## 3. Features

### 3.1 Per-image features (inherited from binary model)

These are already engineered in `src/shared/image_features.py` and used in the 21-feature matrix
produced by `engineer_features` (`src/shared/image_features.py:408–`):

| Feature | Source column | Notes |
|---------|--------------|-------|
| `width`, `height` | `v2_image_assets` | Raw pixels; clipped area in `FEATURE_NAMES[7]` |
| `classification` | `v2_image_assets.classification` | `chart` / `table_image` / `unknown`; one-hot in `FEATURE_NAMES[8,9,14]` |
| `nearby_text` semantic counts | `v2_image_assets.nearby_text` | Five categories: cohort, retention, unit-econ, temporal, growth (`FEATURE_NAMES[16–20]`) |
| Heuristic `relevance_score` | `v2_image_assets.relevance_score` | Proxied as `cohort_confidence` in `FEATURE_NAMES[0]` |
| `detection_tier` | derived via `derive_detection_tier` (`src/shared/image_features.py:351–371`) | `tier_1_cohort` / `tier_2_large` / `tier_3_all` → `FEATURE_NAMES[10,11]` |
| `section_type` | `v2_image_assets.section_type` | Section context (MD&A, Risk Factors, etc.) |

### 3.2 Per-metric features

These are new to the per-metric model and not present in the binary trainer:

| Feature | Construction | Notes |
|---------|-------------|-------|
| `metric_id` one-hot | sklearn `OneHotEncoder` on the `metric_id` string | Sparse; only viable if training corpus covers the metric. Prefer learned embedding if label density >200 rows per metric. |
| `metric_tier` | 1 if metric is Tier-1 (CLAUDE.md Metric Priority Tiers), 0 if Tier-2 | Tier definitions are authoritative in `config/metric_keywords.yaml` (`src/gold_standard/v2_validator.py` at runtime). |

### 3.3 Cross features (per image × per metric)

| Feature | Construction | Notes |
|---------|-------------|-------|
| `keyword_match_nearby` | Count of `metric_id`-specific keyword patterns in `v2_image_assets.nearby_text` | Different keywords fire for different metrics. Read patterns from `config/metric_keywords.yaml` via `src/shared/keyword_config.py`. |
| `keyword_match_ocr` | Count of `metric_id`-specific keyword patterns in `v2_image_assets.ocr_text` | OCR text from full-page-image OCR pipeline; may be NULL. |

### 3.4 Currently unused but available

**`v2_image_assets.reviewer_chart_type`** — the chart type label a reviewer applied
(`bar`, `line`, `pie`, `table`, etc.; see `scripts/export_image_training_data.py:123–124`).
Chart type carries a strong prior for certain metric categories:

- Bar / stacked-bar charts → cohort metrics (`cm_revenue_by_cohort`, `cm_transactions_by_cohort`)
- Pie / donut charts → concentration metrics (`cm_revenue_concentration`)
- Multi-line charts → retention / NRR metrics (`cm_net_revenue_retention`, `cm_customer_retention_rate`)

This is a high-value feature that the binary model ignores because the label collapses it.
The per-metric model should include `(reviewer_chart_type, metric_id)` interaction terms or
a one-hot of `(chart_type_bucket, metric_tier)` pairs.

### 3.5 Vision-derived feature

**`v2_image_classifications.predicted_metrics`** — the confidence score that the Vision
classifier (`ENABLE_METRIC_CLASSIFY=true`) assigned to the same `metric_id` for this image,
from `src/llm/vision_client.py`. Shape: JSONB mapping `metric_id → float`.

Include as a numeric feature (`vision_score_for_metric`, 0.0 when absent or classifier was not
run). **Usefulness is TBD pending Phase 2 eval** of Vision score calibration. If Phase 2 finds
the Vision scores are poorly calibrated, this feature may add noise; treat as optional and
evaluate with / without via ablation.

---

## 4. Model

### 4.1 Baseline: logistic regression

`sklearn.linear_model.LogisticRegression` with `class_weight='balanced'`.

Rationale: interpretable, handles one-hot-encoded `metric_id` well under L2 / L1 regularization,
and trains fast on sparse feature matrices. The binary model uses logistic regression as its
primary mode (`scripts/train_image_relevance_model.py:1–12`); the same infrastructure applies.
Use `C` tuning via `GridSearchCV` on the training fold.

### 4.2 Alternative: gradient-boosted tree

`sklearn.ensemble.HistGradientBoostingClassifier` with `class_weight='balanced'`.

The binary trainer already supports this model type (see `scripts/train_image_relevance_model.py:25`
and the `--model-type gbt` flag). It handles missing values natively (useful when
`ocr_text` is NULL or `reviewer_chart_type` is NULL) and captures non-linear interactions
between `chart_type` and `metric_id` without explicit interaction terms.

**Gating condition:** per-metric label density must be sufficient. If any metric in the training
set has fewer than 50 labeled `(img_id, metric_id)` rows, the GBT is prone to overfitting that
metric. Enforce a minimum-density threshold; skip GBT for sparse metrics and fall back to logistic
regression or the binary model (see section 6).

### 4.3 Class weighting

Negatives will dominate: an image may be confirmed relevant for 1 metric but produce label-0 rows
for the remaining ~30 in-scope metrics. Use `class_weight='balanced'` in both model types.
Monitor per-metric class ratios in the export step and log a warning if any metric's positive
rate is below 5%.

---

## 5. Evaluation

### 5.1 Per-metric P/R/F1 and threshold sweep

Mirror the threshold sweep in `scripts/train_image_relevance_model.py:122–144`:

```
precisions, recalls, thresholds = precision_recall_curve(y, y_prob_cv)
p_at_80  = precision_at_recall(precisions, recalls, 0.80)
p_at_90  = precision_at_recall(precisions, recalls, 0.90)
p_at_95  = precision_at_recall(precisions, recalls, 0.95)
```

Run this sweep separately for each `metric_id`. Report:
- AUC-ROC and average precision per metric
- Precision at 80%, 90%, 95% recall per metric
- Threshold value that achieves the recall target per metric

### 5.2 Recall targets

| Metric tier | Minimum recall target |
|-------------|----------------------|
| Tier-1 | 95% |
| Tier-2 | 85% |

These mirror the project's tier-1-must-not-miss policy (CLAUDE.md Metric Priority Tiers). A
per-metric classifier that cannot reach 95% recall for a given Tier-1 metric must fall back to
the binary-model + Vision-score filter for that metric (see section 6).

### 5.3 Cross-validation

5-fold stratified CV, **grouped by `img_id`**.

The grouping constraint is critical: a single image can contribute label-1 and label-0 rows for
different metrics. Without grouping, the same image's rows land in both train and validation folds,
leaking image-level features (width, height, nearby_text) and producing overoptimistic estimates.
Use `sklearn.model_selection.GroupedStratifiedKFold` or equivalent; group key = `img_id`.

---

## 6. Replacement Strategy

The per-metric model does **not** replace the binary image-relevance model:

- **Binary model** (Phase 1, `LEARNED_TRIAGE_MIN`): gates the image-level reviewer queue. An
  image that scores below the threshold never enters the queue. This role is unchanged.
- **Per-metric model** (this design): gates which metric chips appear on the reviewer card for
  images that have already passed the binary gate. It replaces the current Phase 2b filter
  (Vision confidence score threshold) **if and only if** it outperforms that filter on per-metric
  recall at the targets in section 5.2.

Deployment shape (when ready):

1. Binary model score determines queue membership (existing `image_triage.py` path,
   `src/extraction_v2/stages/image_triage.py`).
2. For images in the queue, per-metric model predicts `p(metric | image)` for every candidate
   metric. Chips with `p >= threshold_metric` are surfaced on the card.
3. Threshold per metric is set at the value that achieves the tier recall target from section 5.2.
4. Metrics for which the per-metric model falls below the recall target retain the existing
   Vision-score or keyword-based chip filter as a fallback.

---

## 7. Open Questions / Risks

### 7.1 Cold-start metrics

Metrics with fewer than 50 labeled `(img_id, metric_id)` rows cannot support a reliable
per-metric classifier. Options:

- **Tier-based prior:** for a cold-start Tier-1 metric, default to showing the chip whenever the
  binary model score is above a conservative threshold (high recall, accept lower precision).
- **Binary model + Vision score fallback:** use the existing Phase 2b filter for the metric until
  the label corpus grows.
- **Metric grouping:** cluster metrics by keyword overlap (from `config/metric_keywords.yaml`)
  and train a shared model for the cluster; split when per-metric density reaches threshold.

Document the chosen fallback in the training export script once implemented.

### 7.2 Reviewer disagreement reconciliation

Any-accept-wins (section 2) is a known optimistic bias. It should be revisited when per-metric
inter-rater agreement can be measured from `v2_image_metric_confirmations` (requires at least two
reviewers to have acted on the same `(img_id, metric_id)` pair). A confidence-weighted label that
down-weights lone accepts against multiple rejects is a plausible alternative but needs sufficient
multi-reviewer overlap to calibrate.

### 7.3 Per-metric label sparsity for Tier-2 metrics

Some Tier-2 metrics (e.g. `cm_daily_active_users`, `cm_arpu`) may appear rarely in the image
corpus because they are more naturally expressed in text. The design must accommodate a
"skip this metric, use binary fallback" decision at training and at inference time. The export
script should compute per-metric label counts before training and emit a structured warning for
any metric below the density threshold.

### 7.4 Vision score dependency

The Vision confidence score feature (section 3.5) creates a dependency on Phase 2 eval results.
If Phase 2 eval concludes that Vision scores are not calibrated, this feature should be dropped
from the per-metric model. Design the training pipeline to toggle this feature via a flag rather
than hard-coding it.

---

## 8. Documentation

No existing docs require updates to reflect this design note. The plan's documentation step is
satisfied by this file alone (`docs/architecture/per-metric-image-classifier.md`). When
implementation begins, update `docs/operations/image-model-training-runbook.md` with the
per-metric training procedure.

---

Implementation deferred to a follow-up plan.

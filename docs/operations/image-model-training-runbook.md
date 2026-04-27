# Image Relevance Model Training Runbook

## Overview

The image relevance model is a scikit-learn classifier that scores SEC filing and presentation images for likelihood of containing a customer metric chart. Training data comes from two sources:

| Source | Location |
|--------|----------|
| SEC filing image review decisions | PostgreSQL `v2_image_review_decisions` table (legacy, read-only) |
| 8-K presentation image review decisions | `data/presentation_gold_standard/_image_decisions.json` |
| S-1/F-1/10-K filing image review decisions | `data/filing_gold_standard/_image_decisions.json` |

Trained model and supporting files are written to `data/image_model/`.

---

## When to Retrain

- After completing a batch of image review decisions (SEC or presentation)
- After adding new presentation image candidates to the gold standard set


---

## Prerequisites

- `DATABASE_URL` set in `.env` (required to read SEC image review decisions)
- Presentation gold standard candidate files present in the appropriate directory:
  - 8-K: `data/presentation_gold_standard/{key}_image_candidates.json`
  - S-1/F-1/10-K: `data/filing_gold_standard/{key}_image_candidates.json`
- Corresponding `_image_decisions.json` present and populated in each directory used

---

## Step 0: Image Dimensions (no longer needed)

The V2 extractor (`batch_v2_extraction.py`) captures `width` and `height` on `v2_image_assets` at extraction time, so a separate dimension-backfill step is no longer required. (The V1 `backfill_image_dimensions.py` script was removed in the Phase B V1 image-review retirement.)

Proceed directly to **Step 1**.

---

## Step 1: Generate Missing Image Candidate Files

Skip this step if all presentations already have `_image_candidates.json` files.

Run when adding a new presentation ticker that hasn't been preannotated yet, or when a ticker has been reviewed but lacks a `_image_candidates.json` file.

```bash
# For 8-K presentations (earnings releases)
python3 scripts/preannotate_presentations.py --ticker <TICKER> --images-only

# For S-1/F-1/10-K filings
python3 scripts/preannotate_presentations.py --ticker <TICKER> --filing-type S-1 --images-only
```

- Uses cached HTML; no network requests needed if the filing was already fetched
- `--images-only` skips CSV generation and uses `_image_candidates.json` as the idempotency check
- Image IDs are deterministic (`uuid5` based on filing + XPath locator), so **re-running this is safe** — it produces the same IDs and existing decisions are not affected

**How to detect tickers that need this step:** the export script (Step 2) emits "No candidate found" warnings for any decision keys without a matching candidate JSON.

---

## Step 2: Export Training Data

```bash
python3 scripts/export_image_training_data.py
```

Reads decisions from the database and `_image_decisions.json`, joins them against the corresponding candidate files, and writes `data/image_model/training_data.csv`.

**Check the output for:**
- "No candidate found" warnings — should be 0. If any appear, run Step 1 for the affected ticker and re-run this step.
- Per-source row counts (SEC vs. presentation) — note these for comparison after the next retrain.

**Available feature: `detected_keywords`** (persisted on `v2_image_assets`, migration `sql/32`).
Each row carries the sorted, unique set of metric-keyword strings matched at the time
the image was extracted — a time-stamped snapshot of what the reviewer saw at decision
time. Prefer this column over re-deriving keywords from `nearby_text` at training time:
`config/metric_keywords.yaml` evolves, and re-deriving would disagree with the YAML
that surfaced the image. NULL on pre-backfill rows; run
`python3 scripts/backfill_image_keywords.py` once to populate historical data.

---

## Step 3: Train Model

```bash
python3 scripts/train_image_relevance_model.py
```

Trains a logistic regression and gradient-boosted tree (GBT) classifier, evaluates both on a held-out split, and writes results to `data/image_model/model_report.txt`.

**Compare metrics against the previous report before accepting:**

| Metric | Logistic baseline | GBT baseline |
|--------|------------------|--------------|
| AUC-ROC | 0.823 | 0.769 |
| AP | 0.584 | 0.449 |

A drop in AUC-ROC or AP indicates the new training data may contain labeling errors or the class balance has shifted. Investigate before deploying.

---

## Step 4: Score Database Candidates

```bash
python3 scripts/score_image_candidates.py --rescore-all
```

Applies the newly trained model to all image candidates in the database and updates their relevance scores. `--rescore-all` forces rescoring even for candidates that already have a score.

---

## Files Produced

| File | Description |
|------|-------------|
| `data/image_model/training_data.csv` | Exported feature matrix used for training |
| `data/image_model/relevance_model.joblib` | Serialized trained model (loaded at runtime) |
| `data/image_model/model_report.txt` | Evaluation metrics from the most recent training run |

---

---

## Expanding Training Data

Current dataset size: 584 samples (66 relevant, 11.3% positive rate). Every additional labeling batch from a new company directly improves model generalization.

### Check labeling status

```bash
python3 scripts/image_labeling_status.py          # show unlabeled queue
python3 scripts/image_labeling_status.py --all    # include fully labeled filings
```

The script ranks unlabeled filings by priority:
1. **New tickers** first — companies not yet represented in any labeled data maximize diversity
2. **S-1/F-1/10-K** before 8-K — registration filings have far more charts than earnings releases
3. **Candidate count** — more images per session = more efficient use of review time

### Workflow for adding a new presentation ticker

```bash
# 1. Generate candidates (if not already present)
python3 scripts/preannotate_presentations.py --ticker <TICKER> --filing-type S-1 --images-only

# 2. Label via the web UI
#    http://localhost:5001/review/pres-images/

# 3. Retrain (Steps 2–4 of this runbook)
python3 scripts/export_image_training_data.py
python3 scripts/train_image_relevance_model.py
python3 scripts/score_image_candidates.py --rescore-all
```

### Dataset size milestones

| Samples | Positive | Goal |
|---------|----------|------|
| 584 | 66 (11%) | Baseline |
| 800 | ~100 | First meaningful generalization gains |
| 1000 | ~130 | Reliable AUC improvement expected |
| 1500+ | ~200 | Sufficient for GBT to outperform LR |

### Class balance monitoring

After retraining, check `data/image_model/model_report.txt`:
- Positive rate should be **≥ 10%** — if it drops below, the new batch skewed toward negatives
- If AUC-ROC drops > 0.02 from baseline (0.823), inspect the new training rows for labeling errors

---

## Troubleshooting

**"No candidate found" warnings during export**
A `_image_candidates.json` file is missing for one or more filing keys. Run Step 1 (`--images-only`) for each affected ticker, then re-run Step 2.

**Metrics drop after retraining**
Check for conflicting labels in the new decisions (same image labeled both relevant and irrelevant across sessions), or a large shift in class balance. Inspect `data/image_model/training_data.csv` for anomalies before committing the new model.

**`DATABASE_URL` not set**
SEC decisions will not be exported. Set `DATABASE_URL` in `.env` and re-run Step 2.

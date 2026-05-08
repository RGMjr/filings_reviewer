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

---

## UI-triggered retrains (queue + worker, gh-400)

The "Update Image Classifier" button on `/v2/review/stats` enqueues a `model_training_runs` row and the `filings-onboarding-runner` Render worker drains it. The web POST never owns the lifetime of the work — Render container recycles can no longer SIGKILL a retrain mid-run because the work runs on a long-lived worker process, not on a gunicorn web worker.

| Mode | Trigger | INSERT status | Spawn | Where work runs |
|------|---------|---------------|-------|-----------------|
| Prod (`RETRAIN_SPAWN_SUBPROCESS=false`, set in `render.yaml`) | UI button | `'queued'` | none | `filings-onboarding-runner` worker |
| Dev/test (`RETRAIN_SPAWN_SUBPROCESS=true`, default) | UI button or curl | `'running'` | detached `subprocess.Popen` | gunicorn web worker (subprocess) |
| CLI (always) | `python3 scripts/retrain_image_triage.py …` | n/a | n/a | the shell that ran the script |

The `GET /api/v2/models/training/<uuid>/status` poll endpoint surfaces `queued`, `running`, `succeeded`, or `failed`; the UI treats `queued` and `running` identically as "in flight".

### Debugging a stuck retrain

1. **Read the row.** `psql -c "SELECT id, status, started_at, run_lock_until, error FROM model_training_runs WHERE id = '<uuid>'"`.
2. **`status='queued'` and `run_lock_until` NULL/past.** The worker has not picked the row up. Check Render dashboard → `filings-onboarding-runner` → Logs for the most recent `Entering watch mode` line and any tracebacks. If the worker is down, restart it.
3. **`status='running'` and `run_lock_until` in the future.** Worker is actively running the script — do nothing. Tail the per-run log in `logs/retrain_<run_id>.log` on the worker if available.
4. **`status='running'` and `run_lock_until` past.** Worker died mid-run. The web-side gh-392 sweep flips this to `failed` on the next button-click; manual reset:
   ```sql
   UPDATE model_training_runs
      SET status = 'failed',
          error  = 'manual cleanup',
          completed_at = NOW(),
          run_lock_until = NULL
    WHERE id = '<uuid>';
   ```
5. **Click again.** With the row no longer at `queued`/`running`, the concurrency gate clears and the next click enqueues a fresh row.

---

## Phase 2 — Vision Per-Metric Score Calibration Eval

`scripts/evaluate_vision_metric_scores.py` is a read-only offline eval that
measures whether the confidence scores emitted by the Vision metric-classify
step (`v2_image_classifications.predicted_metrics`) are calibrated enough to
filter on.  **It does not modify any production data or route.**

### When to run

Run this script once a sufficient volume of per-metric reviewer decisions has
accumulated in `v2_image_metric_confirmations` (a few hundred labeled images is
a reasonable minimum).  Re-run after any substantial labeling session to check
whether score calibration has shifted.

### Usage

```bash
# Write the report to the default path.
python3 scripts/evaluate_vision_metric_scores.py \
    --database-url "$DATABASE_URL" \
    --output data/vision_score_eval/report.txt

# Preview to stdout without writing (useful during testing).
python3 scripts/evaluate_vision_metric_scores.py --database-url "$DATABASE_URL" --dry-run

# Limit rows fetched during development.
python3 scripts/evaluate_vision_metric_scores.py --database-url "$DATABASE_URL" --limit 500
```

### What the report contains

| Section | Description |
|---------|-------------|
| Header counts | Total labeled (img_id, metric_id) pairs, positives, negatives, positive rate |
| AUC-ROC | Overall discriminative power across all metrics |
| Average Precision | Area under the precision-recall curve |
| Threshold sweep | Precision / recall / F1 at thresholds 0.1–0.9 |
| Per-metric breakdown | AUC and AP per metric, shown only where ≥30 positive labels exist |

### How to interpret the output

**AUC-ROC:**

| AUC | Interpretation |
|-----|---------------|
| < 0.70 | Scores not calibrated — do not filter |
| 0.70–0.80 | Marginal — review per-metric breakdown before deciding |
| ≥ 0.80 | Proceed to Phase 2b gating decision |

**Phase 2b trigger condition (from the approved plan):**
AUC ≥ 0.80 AND a threshold exists with ≥95% recall AND ≥40% precision.
If the condition is met, open a Phase 2b PR to apply the filter at the
`predicted_metrics` emission site in `src/web/routes/api_unified.py`.
If not met, stop and revisit after Phase 3 (per-metric classifier) ships.

**Threshold sweep:**
Choose the threshold row where recall is closest to 0.95 (from above), then
read the corresponding precision.  If precision ≥ 0.40, the filter is viable.

**Per-metric breakdown:**
Low AUC on a specific metric indicates the Vision model's score is noisy for
that metric class.  Metrics below the breakdown threshold (< 30 positives)
cannot be evaluated reliably.

### Results

| Run date | N pairs | AUC-ROC | AP | Phase 2b trigger met? |
|----------|---------|---------|-----|----------------------|
| 2026-05-08 | 382 (45 pos / 337 neg) | 0.7893 | 0.5863 | **No** — AUC < 0.80 and best precision at ≥95% recall is 18% (need ≥40%) |

The 2026-05-08 run was the first trustworthy result. An earlier run produced spurious AUC=1.0 / AP=1.0 because of a list-comprehension destructuring bug in `generate_report` (gh-577, fixed in PR #579). Phase 2b is on hold until either AUC organically crosses 0.80 with more reviewer data, or the per-metric model from PR #560 supersedes this filter approach.

## Phase 1 — Binary Image Relevance Triage Gate

The binary relevance model (Step 3 above) gates the image-level reviewer queue. When `USE_LEARNED_TRIAGE=true`, images with `predicted_relevance < LEARNED_TRIAGE_MIN` are not enqueued for review. The gate is a **soft skip**: rows still persist to `v2_image_assets`, so the gate is fully reversible by env-flip with no data loss.

Code paths:
- Gate check: `src/extraction_v2/stages/image_triage.py:52–57, 658–677`
- Score computation: `src/shared/image_features.py::predict_relevance`
- Threshold values are emitted in the model report by `scripts/train_image_relevance_model.py:130–145`

### Rollout history

| Date (UTC) | `USE_LEARNED_TRIAGE` | `LEARNED_TRIAGE_MIN` | Rationale |
|------------|----------------------|----------------------|-----------|
| Pre-2026-05-08 | `false` | — | Gate not enabled; all images enqueued |
| **2026-05-08** | **`true`** | **`0.230`** | Phase 1 rollout. 90%-recall threshold from PR #559 model run (run id `cba5e60f`, 1713 training samples, 76 positives). |

Set in Render env-group `filings-shared-secrets` (per memory `project_render_env_invisible_to_git_audit` — Render env changes are invisible to git, so this runbook is the audit trail).

### Pre-rollout false-negative analysis (2026-05-08)

Before flipping the gate, we enumerated which previously-reviewed images would have been filtered (i.e. `predicted_relevance < 0.230` AND any `accept|correct|add` confirmation), and checked whether the same metrics were captured elsewhere in the same filing.

**Result: 3 FN images out of 70 known positives (95.7% recall in production), and every confirmed metric in those FNs is redundantly captured by text facts in the same filing.**

| # | Image | Score | Filing | Metrics confirmed | Redundant text-fact coverage |
|---|-------|-------|--------|-------------------|------------------------------|
| 1 | GitLab `gitlab-s1xartworkcoverart3a.jpg` | 0.142 | GitLab S-1/A 2021-10-12 | (legacy "relevant" only — no per-metric data) | n/a |
| 2 | GitLab `coverart4ba.jpg` | 0.142 | GitLab S-1/A 2021-10-12 | `cm_net_revenue_retention` (T1), `cm_large_customers_period_end` (T1), `cm_customers_period_end` | NRR: 5 text facts; large_customers: 4; customers_period_end: 4 |
| 3 | Slack `mdaa3.jpg` | 0.227 | Slack S-1/A 2019-05-20 | `cm_customers_period_end` (T2) | 3 text facts + 1 presence row |

The cover-art images are introductory hero pages with marketing-style stat callouts; the same numbers are quoted in prospectus body text, which is where the redundant facts come from. Filtering these images at the image-triage stage does not change the filing-level disclosure picture.

The FN-redundancy check script lives at `/tmp/fn_redundancy_check.py` (was an ad-hoc one-off; not committed). To reproduce, see the SQL in `docs/operations/image-model-training-runbook.md` git history at this commit.

### Watch window — what to monitor

For 2 weeks post-rollout:

- **Reviewer queue volume** in `v2_image_assets WHERE review_status='pending'` should drop noticeably (~50% based on the score distribution).
- **Reviewer "missing image" reports** are the recall-failure signal. Any report where a reviewer expected to see an image but couldn't find it warrants checking `predicted_relevance` for that asset.
- **Positive rate on queued images** in newly-confirmed `v2_image_metric_confirmations` rows should rise — the gate is buying precision at the cost of some recall.
- **`v2_image_assets.predicted_relevance` distribution** for newly-extracted filings should match the training distribution (mostly 0.0–0.3 with a high-confidence tail).

### Tightening to 0.317 (80%-recall threshold)

If the 2-week watch window passes clean (no recall-failure reports), the next step is to tighten the threshold:

```
LEARNED_TRIAGE_MIN=0.317  # ~80% recall, ~72% queue reduction
```

This drops 18 of 90 known positives (per the model report) — more aggressive but recovers more reviewer time. Decide based on observed reviewer load and any false-negative complaints accumulated during the watch window.

### Escape hatch

If anything looks bad:

```
USE_LEARNED_TRIAGE=false
```

In Render env-group `filings-shared-secrets`. The gate at `src/extraction_v2/stages/image_triage.py:52–57` reads the env var per-call (gh-477), so the flip takes effect on the next request without a worker restart. No data loss because every image still persists to `v2_image_assets` regardless of the gate.

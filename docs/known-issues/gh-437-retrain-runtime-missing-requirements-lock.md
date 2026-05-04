---
id: 437
source: gh
slug: retrain-runtime-missing-requirements-lock
title: Retrain dies at startup — requirements.lock missing from runtime Docker image (gh-406 sklearn version check unreachable)
status: resolved
severity: high
autonomy: review
estimated: S
touches:
  - Dockerfile
  - scripts/retrain_image_triage.py
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 437
pr_refs:
  - 439
note: All three layered fixes shipped in PR #439 — Dockerfile runtime stage now COPYs requirements.lock; check_sklearn_version() runs inside the args.run_id try/except so failures write status='failed'; _read_pinned_sklearn_version() catches FileNotFoundError and degrades to a warning. GH issue closed 2026-05-04.
---

### Problem

Every UI-triggered "Update Image Classifier" click on Render now fails within ~40 seconds with `model_training_runs.error='retrain_subprocess_died_no_status'`. The R2 pointer `models/image_relevance/latest_run_id.txt` never gets created, so the model-score sort (#407) silently produces no reordering in prod.

Repro: 2026-05-04 14:17:01 UTC — fresh click → row `failed` at 14:17:41 UTC, no metrics, no model_path.

### Root cause

The sklearn version check shipped in #420 (gh-406) calls `_read_pinned_sklearn_version()` at the top of `scripts/retrain_image_triage.py::main()`, which tries to read `/app/requirements.lock`. The runtime Docker image does not contain that file:

```dockerfile
# Dockerfile, builder stage — bind mount, not COPY:
RUN --mount=type=bind,source=requirements.lock,target=requirements.lock \
    pip install -r requirements.lock
```

`--mount=type=bind` exposes the file only during that single `RUN`. It is not `COPY`'d into the runtime stage. The runtime stage's explicit COPY list covers `src/`, `scripts/`, `sql/`, `config/`, and `data/image_model/relevance_model.joblib` + `model_report.txt` — nothing else.

`FileNotFoundError` propagates up out of `_read_pinned_sklearn_version()` → `check_sklearn_version()`, both called BEFORE the `if args.run_id:` try/except block in `main()`. So the script exits non-zero without writing `status='failed'` to the DB. The worker's poll loop in `src/ml/retrain_runner.py` (introduced in #424) waits its 30s `poll_interval`, observes `rc != 0` with the row still `'running'`, and writes the generic `retrain_subprocess_died_no_status` post-mortem.

40 seconds elapsed = ~2s script crash + 30s poll interval + a few seconds of DB writeback overhead. Matches observed timing exactly.

### Next Steps

Three layered fixes; do all three for belt-and-suspenders:

1. **Dockerfile** (the actual fix): add `COPY --chown=appuser:appuser requirements.lock ./requirements.lock` to the runtime stage. Preserves the version check's intent.
2. **Script error-handling hardening**: move `check_sklearn_version()` *inside* the `if args.run_id:` try/except in `scripts/retrain_image_triage.py` so any future startup-time failure (missing file, malformed pin, etc.) writes a meaningful `status='failed', error=<exc>` row instead of the generic `retrain_subprocess_died_no_status`.
3. **Loader resilience**: `_read_pinned_sklearn_version()` should catch `FileNotFoundError` and degrade to a warning ("requirements.lock not present, skipping version check") rather than hard-exit. Loud but not fatal.

### Verification

- After fix: trigger a retrain via `POST /api/v2/models/image-classifier/retrain` from the stats page.
- Expected: `model_training_runs` row reaches `status='succeeded'` with `num_training_rows ≈ 1499`, `num_positive_rows ≈ 80`, `model_path` of form `models/image_relevance/<run_id>/relevance_model.joblib`.
- `models/image_relevance/latest_run_id.txt` in R2 advances to the new run id.
- Belt-and-suspenders check: temporarily delete `requirements.lock` from the runtime image, re-trigger, confirm the row gets `status='failed'` with a meaningful error string (not the generic `retrain_subprocess_died_no_status`).

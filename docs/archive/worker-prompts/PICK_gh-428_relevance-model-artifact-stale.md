You are working gh-428: refresh the on-disk image-relevance model artifact (`data/image_model/relevance_model.joblib`) so dev / Docker-COPY'd contributors see consistent scoring. The deployed prod model is the freshly retrained `cba5e60f` run (1713 samples, AUC 0.829) — the on-disk artifact in git is the older 808-sample artifact and needs catching up.

## Source of truth

- Fragment: `docs/known-issues/gh-428-relevance-model-artifact-stale.md` (read fully from `origin/main` before planning).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules".
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
- Related context (read for shape, do not modify):
  - `data/image_model/relevance_model.joblib` and `data/image_model/model_report.txt` (the artifacts to refresh)
  - `Dockerfile` runtime stage (the COPY line shipped in #407 hotfix #416 that puts these into the runtime image; verify it's still there)
  - `src/shared/image_features._load_model` (the loader: prod uses R2; dev falls back to disk)
  - `.claude/rules/infrastructure.md` "Model Artifact Storage" section
  - `requirements.lock` (sklearn version pin — the joblib must be pickled by the same sklearn major)
  - `models/image_relevance/cba5e60f-9a99-4231-82e0-fe232c9a9792/relevance_model.joblib` in R2 (the canonical refreshed artifact)

## Status note (read first)

This is a **non-prod hygiene fix**. The prod loader (`R2_BUCKET` set) reads the R2 pointer and materializes per-run joblibs from R2 — it does NOT use `data/image_model/relevance_model.joblib`. So the staleness only affects:

1. Dev contributors running locally without `R2_BUCKET` set (the loader falls back to the on-disk file).
2. The Dockerfile-COPY'd version that ships in the runtime image — this is the explicit fallback for emergencies (e.g., R2 outage).

The stakes are low; this is housekeeping, not an incident. Don't over-engineer.

## Workflow

1. **Verify the staleness is still present.**
   ```bash
   git fetch origin main --quiet
   wc -l data/image_model/training_data.csv
   head -10 data/image_model/model_report.txt   # look for "Training samples: N"
   python3 -c "
   import joblib, sys
   m = joblib.load('data/image_model/relevance_model.joblib')
   print('Loaded OK:', type(m).__name__)
   "
   ```
   Expect the on-disk model report to show ~808 samples; the corpus has ~1713. If they already match (someone else fixed it first), abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

2. **Plan mode.** Use plan mode — touches a binary artifact in git and the local CSV. Run `/plan-review` before exiting. The plan must include the **Documentation** step: update `data/image_model/model_report.txt` (it's always paired with the joblib).

3. **Worktree-first.** First step of implementation: `EnterWorktree gh-428-refresh-on-disk-model`.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT.**
     - `data/image_model/` is NOT in `.gitignore` for the joblib + report files (only `*_pre_backfill.*` patterns are — verify with `git check-ignore -v data/image_model/relevance_model.joblib`).
     - The Dockerfile runtime stage still has `COPY --chown=appuser:appuser data/image_model/relevance_model.joblib ./data/image_model/relevance_model.joblib` (and the model_report). If gh-391 (R2 persistence) removed the COPY, this fragment becomes moot — close as not-applicable.
     - sklearn version: `python3 -c "import sklearn; print(sklearn.__version__)"` must match `requirements.lock` (currently `1.8.0`). If it doesn't, the local-trained joblib won't load on Render. The check shipped in #420 (gh-406) catches this for retrains; you need to verify it manually for this manual artifact refresh.
   - **SCOPE CHECK.** Two files change: `data/image_model/relevance_model.joblib` and `data/image_model/model_report.txt`. Optionally `data/image_model/training_data.csv` if it's also tracked (probably is — confirm with `git ls-files data/image_model/`). Do NOT modify the GBT artifact (`relevance_model_gbt.joblib`) — it's an unused alternate per `cba5e60f` notes.
   - **RULES COMPLIANCE.** `feedback_partial_scope_rename_scoping` doesn't apply. `feedback_check_existing_fragment_before_create` — no new fragment needed; gh-428 already exists.
   - **RISK ASSESSMENT.** What could break:
     - sklearn version mismatch on local: the joblib won't load and the model-score sort silently degrades to None scores. Catch with the version check before commit.
     - The artifact getting larger: the new artifact may differ in size by ~tens of KB. Negligible.
     - Stale Docker layer cache on Render: the COPY line cache invalidates on the file content change, so the next deploy rebuilds the relevant layer. Bounded.
   - **MINIMAL PATH.** Two pulls (joblib + report) + a CSV refresh (if tracked) + commit. No code changes.

5. **Implementation:**

   **5a. Refresh the artifacts.** Two paths:

   *Path A — pull from R2 directly (fastest if you have R2 creds):*
   ```bash
   set -a && source .env && set +a
   aws s3 cp \
     --endpoint-url "$R2_ENDPOINT_URL" \
     "s3://$R2_BUCKET/models/image_relevance/cba5e60f-9a99-4231-82e0-fe232c9a9792/relevance_model.joblib" \
     data/image_model/relevance_model.joblib
   aws s3 cp \
     --endpoint-url "$R2_ENDPOINT_URL" \
     "s3://$R2_BUCKET/models/image_relevance/cba5e60f-9a99-4231-82e0-fe232c9a9792/model_report.txt" \
     data/image_model/model_report.txt
   aws s3 cp \
     --endpoint-url "$R2_ENDPOINT_URL" \
     "s3://$R2_BUCKET/models/image_relevance/cba5e60f-9a99-4231-82e0-fe232c9a9792/training_data.csv" \
     data/image_model/training_data.csv
   ```
   Verify the run id matches what's in `models/image_relevance/latest_run_id.txt` in R2 (in case it advanced since this fragment was filed).

   *Path B — re-train locally against prod DB:*
   ```bash
   python3 scripts/retrain_image_triage.py --database-url "$DATABASE_URL"
   ```
   Produces fresh artifacts on disk that should match (or improve on) what's in R2. This is more work but exercises the full retrain pipeline locally — a useful sanity check.

   **Recommendation: Path A.** Lower-effort, deterministic, matches what's actually serving prod.

   **5b. Verify the joblib loads under pinned sklearn.**
   ```bash
   python3 -c "
   import sklearn, joblib
   m = joblib.load('data/image_model/relevance_model.joblib')
   print('sklearn:', sklearn.__version__)
   print('model:', type(m).__name__)
   from src.shared.image_features import predict_relevance, v2_row_to_features_input
   row = {'nearby_text':'cohort','width':800,'height':600,'relevance_score':0.7,'classification':'chart','filename':'g123.jpg'}
   print('score:', predict_relevance(v2_row_to_features_input(row)))
   "
   ```
   Expect `sklearn: 1.8.0` and a non-None score. If the score is None, the joblib + sklearn pinned version are incompatible — re-pull from R2 OR retrain in a venv installed from `requirements.lock`.

   **5c. Update fragment frontmatter.** When the PR is created, update the gh-428 fragment to `status: resolved` with `pr_refs: [<PR#>]` (per memory: list of ints).

6. **Verification:**
   - `python3 -c "import joblib; m = joblib.load('data/image_model/relevance_model.joblib'); print(m)"` — loads cleanly.
   - `head -10 data/image_model/model_report.txt` — shows the new sample count (~1713) and AUC.
   - `pytest tests/unit/web/test_image_sort_model_score.py tests/unit/shared/ -x -q` — existing tests still green.
   - Optional Docker smoke: `docker build -t filings-test . && docker run --rm filings-test python3 -c "import joblib; m = joblib.load('data/image_model/relevance_model.joblib'); print('OK')"` — confirms the new artifact rides into the image.

7. **Commit + PR** via `/commit-proj`. PR description should:
   - Reference gh-428 + the cba5e60f run id
   - Note the sample count delta (808 → 1713) and AUC delta
   - Note that prod was already on the new model via R2; this is dev / Docker-fallback hygiene
   - After merge: update the fragment to `status: resolved` with `pr_refs: [<PR#>]`

## Notes for the implementer

- The R2 pointer may have advanced since `cba5e60f`. Always read `models/image_relevance/latest_run_id.txt` first, then pull THAT run's artifacts (not `cba5e60f` if it's superseded).
- Do NOT trigger a fresh retrain via the UI as part of this PR — that would create unnecessary churn. The R2 artifact is canonical; mirror it.
- If gh-391 (R2 persistence) was rolled back and the loader is re-reading from disk in prod, this fragment becomes a high-priority production bug, not a hygiene fix. Verify the R2 read path is still active before treating this as housekeeping.
- gh-426 is a related-but-separate fragment about preventing this drift in the future. Don't try to fix gh-426 in this PR.

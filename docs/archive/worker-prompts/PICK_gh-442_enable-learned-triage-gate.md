You are working gh-442: enable the learned-triage gate in prod by setting `USE_LEARNED_TRIAGE=true` in `render.yaml` (and choosing a deliberate `LEARNED_TRIAGE_MIN`). The retrained image-relevance model (run `cba5e60f`, 1713 rows / 76 positive, AUC 0.829) is currently serving the UI model-score sort but does NOT gate extraction.

## Source of truth

- Fragment: `docs/known-issues/gh-442-enable-learned-triage-gate.md` (read fully from `origin/main` before planning).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules".
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
- Related context (read for shape, do not modify):
  - `render.yaml` (the env vars to add on `filings-extraction`)
  - `src/extraction_v2/stages/image_triage.py` (lines ~46 for the `_USE_LEARNED_TRIAGE` / `_LEARNED_TRIAGE_MIN` defaults; lines ~600-640 for the gate site)
  - `src/shared/image_features.py` (`predict_relevance`, `_load_model`, the R2 pointer flow)
  - `docs/known-issues/gh-419-predict-relevance-silent-load-error.md` — the prerequisite
  - `.claude/rules/infrastructure.md` "Model Artifact Storage" section
  - The fresh model report in R2: `models/image_relevance/<run_id>/model_report.txt` (current run id from `models/image_relevance/latest_run_id.txt`)

## Status note (read first)

**This is blocked on gh-419** (silent load-error in `_load_joblib_into_cache`). Do not proceed until gh-419 is merged and live in prod. Without gh-419, a corrupt R2 joblib or sklearn drift would silently fall back to the heuristic with no metric or alert — so flipping the gate provides no observable signal that it actually became active.

The fragment includes the prereq check as step 1 of "Next Steps." Don't skip it.

## Workflow

1. **Verify gh-419 is merged.**
   ```bash
   git fetch origin main --quiet
   git log origin/main --grep "gh-419" --oneline | head -3
   grep -nE "FileNotFoundError|metric|alert" src/shared/image_features.py | head -10
   ```
   The fragment for gh-419 should be `status: resolved` with `pr_refs` populated. If not, abort — work on something else first.

2. **Read the new model's PR curve.** The current R2 pointer is `cba5e60f` (verified 2026-05-04). Either:
   - Use the AWS CLI / boto3 to fetch `models/image_relevance/cba5e60f-9a99-4231-82e0-fe232c9a9792/model_report.txt` from R2 (creds in `.env` — `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`)
   - Or trigger a fresh local retrain against prod DB (`python3 scripts/retrain_image_triage.py --database-url "$DATABASE_URL"`) and read the on-disk `data/image_model/model_report.txt`. (This is also a useful exercise to confirm the local training environment matches prod.)

   Write down: precision @ 80% recall, threshold for ~80% recall, AUC. Compare against the current `LEARNED_TRIAGE_MIN=0.4` default. Per the gh-442 fragment, the 80%-recall point is around 0.32 — if this is still true, dropping the threshold to 0.32 recovers ~15% more positives at some precision cost.

3. **Plan mode.** Use plan mode — touches infra (`render.yaml`) and is a deliberate behavior change. The threshold value is a judgment call; document the rationale. Run `/plan-review` before exiting. The plan must include the **Documentation** step: `.claude/rules/infrastructure.md` env-vars table and `.claude/rules/web.md` (if `USE_LEARNED_TRIAGE` is mentioned there) need to learn that prod is now on.

4. **Worktree-first.** First step of implementation: `EnterWorktree gh-442-enable-learned-triage-gate`.

5. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT.** Re-confirm:
     - `USE_LEARNED_TRIAGE` is genuinely unset in `render.yaml` for every service (`grep -n USE_LEARNED_TRIAGE render.yaml` should return zero hits).
     - The default in `src/extraction_v2/stages/image_triage.py:46` is still `false`.
     - The R2 pointer matches an actual `succeeded` `model_training_runs` row.
   - **SCOPE CHECK.** This PR adds `USE_LEARNED_TRIAGE=true` (and optionally `LEARNED_TRIAGE_MIN=<value>`) to the `filings-extraction` cron service in `render.yaml`. Do NOT also enable it on `filings-onboarding-runner` or `filings-reviewer` — those services don't run extraction; the gate only matters where `image_triage.py` runs. Do NOT also flip `ENABLE_METRIC_CLASSIFY` (that's gh-441, separate concern). Do NOT modify `image_triage.py` defaults — keep prod overrides explicit in `render.yaml` so future operators see them.
   - **RULES COMPLIANCE.** `project_render_env_invisible_to_git_audit` — verify the new env var actually takes effect post-deploy by checking the Render dashboard env tab, not just the YAML. If env-group overrides shadow it, fix at the env-group level.
   - **RISK ASSESSMENT.** What could break:
     - Extraction begins dropping images below threshold. If the threshold is too high, useful charts get filtered. The A/B verification (step 5c) catches this.
     - The R2 pointer becomes a single point of failure for extraction. gh-419 is the prereq for observability of this failure mode.
     - Per-image latency adds the model-load + scoring time. Pipeline cache (per-worker module cache in `image_features.py`) makes this cheap after the first call.
   - **MINIMAL PATH.** YAML change only. Optional one-line note in `.claude/rules/infrastructure.md` env table.

6. **Implementation:**

   **6a. `render.yaml`** — add to the `filings-extraction` cron service env block:
   ```yaml
   - key: USE_LEARNED_TRIAGE
     value: "true"  # gh-442: gate extraction on the learned relevance model (R2 pointer in models/image_relevance/latest_run_id.txt)
   - key: LEARNED_TRIAGE_MIN
     value: "0.32"  # gh-442: tuned to ~80% recall on the cba5e60f model — adjust based on PR curve in step 2
   ```
   Pick the actual `LEARNED_TRIAGE_MIN` value based on what step 2 told you. Document the choice in the commit message: "Picked X based on the cba5e60f PR curve: precision Y at recall Z".

   **6b. `.claude/rules/infrastructure.md`** — find the env-vars table; update the `USE_LEARNED_TRIAGE` row description if it currently says "off in prod" or similar. Add a note that prod uses the chosen threshold.

7. **Verification** (post-merge, post-Render-deploy):
   - Wait for next `filings-extraction` cron run (daily 6am UTC) or trigger manually.
   - **First gate signal**: `SELECT COUNT(*) FROM v2_image_assets WHERE created_at > NOW() - INTERVAL '24 hours' AND predicted_relevance IS NOT NULL;` — should be > 0 (proves the gate is active and writing scores).
   - **Drop rate**: compare candidate-image counts pre/post-flip:
     ```sql
     SELECT DATE(created_at), COUNT(*) FROM v2_image_assets
       WHERE classification NOT IN ('decorative','logo','signature')
         AND created_at > NOW() - INTERVAL '7 days'
       GROUP BY 1 ORDER BY 1;
     ```
   - **A/B accept rate**: `SELECT DATE(created_at), COUNT(*) FILTER (WHERE decision IN ('accept','correct','add'))::float / COUNT(*) AS accept_rate FROM v2_image_metric_confirmations WHERE created_at > NOW() - INTERVAL '14 days' GROUP BY 1;` — confirm post-flip accept rate at least matches pre-flip.
   - **gh-419 sanity**: confirm zero "learned triage model failed to load" alerts in the worker logs. Confirms the gate is genuinely active, not silently no-op.

8. **Commit + PR** via `/commit-proj`. PR description should:
   - Reference gh-442
   - Document the chosen `LEARNED_TRIAGE_MIN` and the recall/precision trade-off behind it
   - Note that gh-419 is the observability prereq and confirm it's in place
   - Reference the R2 pointer / run id that the gate will load
   - After merge: update the gh-442 fragment to `status: resolved` with `pr_refs: [<PR#>]`

## Notes for the implementer

- Do NOT trigger a fresh retrain via the UI as part of this PR. The current `cba5e60f` model is fine; flip the gate against it. If you need a fresher model, file a separate fragment.
- The `LEARNED_TRIAGE_MIN` value is a deliberate trade-off, not a default to copy. Read the PR curve, pick a point, document the choice. Future operators will read your commit message to understand why.
- Don't be alarmed if the post-flip per-batch image count drops 10-20%. That's the gate doing its job.
- This is a one-way deploy in the sense that pre-flip filings won't be re-scored. Their `predicted_relevance` stays NULL forever unless someone runs a backfill (out of scope).

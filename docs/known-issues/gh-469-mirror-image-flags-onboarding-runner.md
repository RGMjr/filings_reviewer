---
id: 469
source: gh
slug: mirror-image-flags-onboarding-runner
title: Mirror image-extraction env flags onto filings-onboarding-runner (gh-441/gh-442 scope gap)
status: resolved
severity: high
autonomy: review
estimated: S
touches:
  - render.yaml
  - .claude/rules/infrastructure.md
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 469
note: PRs #444 and #462 missed that filings-onboarding-runner runs process_filing inline during ingest; new image flags need to be mirrored or ingest-path filings get NULL predicted_relevance and zero v2_image_classifications rows
---

### Problem

PRs #444 (gh-441 / `ENABLE_METRIC_CLASSIFY`) and #462 (gh-442 / `USE_LEARNED_TRIAGE` + `LEARNED_TRIAGE_MIN`) both added the new image-extraction env vars only to the `filings-extraction` cron service. Both PR descriptions claimed `filings-onboarding-runner` doesn't run the triage stage — but it does.

`src/universe/onboarding.py:782` imports `process_filing` from `src.extraction_v2.pipeline` and invokes it inline at line 847 for every newly-fetched filing during a discover+ingest run. The pipeline reads `USE_LEARNED_TRIAGE` and `ENABLE_METRIC_CLASSIFY` per-call (`pipeline.py:502`, `image_triage.py` module gate), so the gates ARE evaluated — but they read from the worker's environment, where they're unset on `filings-onboarding-runner`.

Net effect of any UI-triggered ingest right now:
- `IMAGE_TRIAGE` uses the heuristic, NOT `predict_relevance`. Newly-ingested images get `predicted_relevance = NULL`.
- `IMAGE_CLASSIFY` stage isn't appended to the pipeline. No new rows in `v2_image_classifications` for ingest-derived filings.

The cron is not a fallback. `filings-extraction` filters by `status='fetched'` (`render.yaml:56`); ingest produces `status='extracted'` rows, so the cron skips them. Picking up the new flags retroactively requires explicit force-reextract via `/ingest/batch/<id>/reextract`.

### Next Steps

1. Mirror six env vars from `filings-extraction` onto `filings-onboarding-runner` in `render.yaml`:
   - `USE_LEARNED_TRIAGE=true`
   - `LEARNED_TRIAGE_MIN=0.32`
   - `ENABLE_METRIC_CLASSIFY=true`
   - `VISION_CLASSIFY_PROVIDER=gemini`
   - `VISION_CLASSIFY_MODEL=gemini-2.5-flash-lite`
   - `VISION_CLASSIFY_THRESHOLD=0.5`
2. Make `GEMINI_API_KEY` available on `filings-onboarding-runner` — currently only on `filings-extraction`. Cleanest path: add to the `filings-shared-secrets` env group rather than duplicating per-service. Note `sync: false` still requires manual entry in the Render dashboard (`project_render_env_invisible_to_git_audit`).
3. After deploy: trigger a small ingest (1–2 filings) via `/ingest/` UI; confirm `v2_image_assets.predicted_relevance IS NOT NULL` and a corresponding `v2_image_classifications` row exists for one of the new images.
4. Document in `.claude/rules/infrastructure.md` that BOTH `filings-extraction` (cron) and `filings-onboarding-runner` (worker) need these flags. Record the trap so future operators don't re-introduce the asymmetry.
5. Decide whether to backfill: ingest runs that happened between gh-441/gh-442 deploy and this fix landed produced filings without scores. Either re-extract with `force=True` (the `/ingest/batch/<id>/reextract` UI handles this — but note the `ReviewedFilingError` guard for any reviewed filings) or accept the gap. Default recommendation: accept the gap unless a specific batch is high-value.

### Same-shaped trap to fix preemptively

`scripts/onboard_tickers.py` CLI also calls `process_filing` directly (line 329). Operators running it locally need the same env vars set in their shell. Optional small fix: warn at the top of the script if both flags are unset (mirrors the gh-426 trailing-warning pattern).

### Verification

- `grep "USE_LEARNED_TRIAGE\|ENABLE_METRIC_CLASSIFY" render.yaml` shows the same set on both `filings-extraction` and `filings-onboarding-runner`.
- After Render redeploy: ingest one filing via UI, query `SELECT predicted_relevance FROM v2_image_assets WHERE filing_id = <id> LIMIT 5;` — values are non-NULL.
- `SELECT COUNT(*) FROM v2_image_classifications WHERE created_at > NOW() - INTERVAL '1 hour';` — at least one row for the newly-ingested filing's chart/table images.
- Worker-log check: zero `ImageTriageStage` "model failed to load" ERROR lines on the onboarding-runner (gh-419 sanity).

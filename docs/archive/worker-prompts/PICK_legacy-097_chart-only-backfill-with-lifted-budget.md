You are working legacy-097: Residual Chart Facts Remain After Chart-Presence Pivot — execute Option 2 (chart-only re-extraction with lifted Vision-OCR budget).

**This is an unusual worker task — it includes a prod-destructive backfill step that CASCADE-destroys 28 reviewer decisions and spends ~$2–$5 on Vision API. Do not skip the explicit user-approval gate before running the backfill.**

## Source of truth
- Fragment: `docs/known-issues/legacy-097-residual-chart-facts-after-presence-pivot.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**. Pay special attention to design principle 6 (reviewed-filing guard) and the chart-presence pivot semantics in principle 4.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules", "Planning Rules", and **"Git Operations"** (destructive-action confirmation rules).
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/v2-pipeline.md` — **authoritative** for `chart_only=True` semantics, the reviewed-filing guard, and the `CHART_BUDGET_PER_FILING_USD` env knob
- `.claude/rules/infrastructure.md` — for `DATABASE_URL` / `TEST_DATABASE_URL` separation and the R2 prod-write guard
- Audit script (already written in the prior session): `scripts/audit_residual_chart_facts.py` — verify it exists at `HEAD`. If missing, the prior session's work didn't get committed; flag and stop.
- Related: `src/extraction_v2/persistence.py::_persist_facts_in_tx` (the `chart_only` branch), `src/extraction_v2/stages/ocr_extraction.py` (`CHART_BUDGET_PER_FILING_USD` env override), `scripts/batch_v2_extraction.py` (`--chart-only`, `--force-reextract`, `--filing-ids-file`).

## The decision (already made)
User picked Option 2 from the legacy-097 triage:

> "Run `chart_only --force-reextract` on the 10 affected filings, but bump `CHART_BUDGET_PER_FILING_USD` for this backfill run only. Get full chart coverage. Higher API spend (~$2–$5). Touches `src/extraction_v2/stages/ocr_extraction.py` env-config — trivial."

The audit (run against prod 2026-04-28) established:
- 10 filings carry residual chart facts (30 rows)
- 28 chart-fact reviewer decisions on those rows (will CASCADE-destroy — intentional)
- 154 chart-classified images across the 10 filings
- 31 of 154 already have `chart_data` populated (cached Vision OCR)
- 146 text-fact reviewer decisions on the same 10 filings (must be preserved — `chart_only=True` scopes the DELETE)
- 3 image-metric confirmations on PYPL filing 1753 (preserved — confirmations are not CASCADE-linked to facts; the "purging" warning text in `_persist_facts_in_tx` is misleading)

The plan is therefore:
1. Re-run the audit to confirm the numbers haven't shifted.
2. Generate the filing-ids file from the audit.
3. **PAUSE FOR EXPLICIT USER APPROVAL** before running the backfill.
4. Run `CHART_BUDGET_PER_FILING_USD=<lifted> python3 scripts/batch_v2_extraction.py --chart-only --force-reextract --filing-ids-file <path>`.
5. Re-run the audit; record outcome.
6. Close the fragment with a Resolution describing the measured outcome.

## Workflow

1. **Verify state on `origin/main`.**
   ```bash
   git fetch origin main --quiet
   ls -la scripts/audit_residual_chart_facts.py            # should exist
   git show origin/main:docs/known-issues/legacy-097-residual-chart-facts-after-presence-pivot.md | head -20
   ```
   Confirm the audit script is committed (or stage it from the local tree if the prior session left it uncommitted — see step 5b). Confirm legacy-097 is still `status: open` with empty `pr_refs`. If anything else has changed (e.g., fragment already closed, audit script absent and untracked locally), stop and re-scope.

2. **Re-run the audit against prod (read-only).**
   ```bash
   set -a && source .env && set +a
   python3 scripts/audit_residual_chart_facts.py
   ```
   Capture the output. Compare to expected (28 chart-fact decisions, 146 text-fact decisions, 3 image confirmations on PYPL 1753, 31 images with `chart_data`, 0 with `detected_metrics`). If any of those numbers have shifted by >5%, stop and surface the delta — recent reviewer work or another backfill may have changed the picture.

3. **Plan mode.** Run `/plan-review` before exiting plan mode. The plan must include:
   - **Documentation step** (per global Planning Rules): a Resolution section in the fragment + optional one-paragraph runbook addition under `docs/operations/` (e.g. `chart-presence-residual-drain.md`, or an inline note in `docs/operations/full-page-ocr-runbook.md`) describing the procedure for future drain-style backfills.
   - **Backfill parameters**: pick `CHART_BUDGET_PER_FILING_USD` value (recommend `2.00` — gives ~8x headroom over default 0.25, comfortably covers all 154 chart images even if Tier-1-keyword bypass under-fires).
   - **Verification SQL**: queries to run post-backfill (chart_fact_count → 0, chart-decision count → 0, text-fact decision count unchanged, image-metric confirmation count unchanged, detected_metrics populated on most chart images).
   - **Rollback plan**: there isn't one. The 28 decisions are gone after the DELETE+CASCADE. State this explicitly so the user is aware before approval.

4. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-097-chart-only-backfill`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

5. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT**:
     - Confirm `scripts/batch_v2_extraction.py` accepts `--chart-only`, `--force-reextract`, and `--filing-ids-file` (grep already confirmed at brief time).
     - Confirm `CHART_BUDGET_PER_FILING_USD` is the right env knob (grep `src/extraction_v2/stages/ocr_extraction.py` for the `os.environ` reference at the line that defaults to `DEFAULT_CHART_BUDGET_PER_FILING_USD`).
     - Confirm `chart_only=True` does NOT delete `v2_image_metric_confirmations` rows (read `_persist_facts_in_tx` lines ~1083–1118 — the secondary guard checks but does not DELETE; the `_persist_images_in_tx` UPSERT preserves `img_id`, so confirmations FK survives).
     - Confirm `_persist_images_in_tx`'s visible→hidden guard does NOT fire for chart→chart re-runs (it only blocks visible→hidden transitions).
   - **SCOPE CHECK**: this PR ships:
     - `scripts/audit_residual_chart_facts.py` (already written; commit only if untracked at HEAD)
     - The fragment closure (status flip + Resolution + pr_refs)
     - Optional: a brief runbook section
     The PR does **NOT** ship code changes to the pipeline, persistence, or `MAX_CHART_CALLS_PER_DOCUMENT` semantics. The budget lift is done via env var at runtime, not as a code change.
   - **RULES COMPLIANCE**:
     - The backfill writes to prod Postgres AND prod R2. `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` must be set for the run (per `.claude/rules/infrastructure.md`). Without it, `_persist_images_in_tx`'s downstream R2 writes will fail (gh-262 territory).
     - The reviewed-filing guard intentionally fires here because of the 28 chart decisions; `--force-reextract` is the documented opt-in.
   - **RISK ASSESSMENT**:
     - 28 reviewer decisions destroyed (intentional, the whole point).
     - 146 text-fact decisions preserved (verified by `chart_only` semantics; verify post-run in step 7).
     - 3 image confirmations preserved (verified by code inspection; verify post-run).
     - ~$2–$5 Vision API spend.
     - Possible re-classification edge: if any chart image gets re-classified into a hidden class on this run, `_persist_images_in_tx` will fire its guard. With `--force-reextract`, it proceeds and logs `force-reextract hiding reviewed images: ...`. Watch for this in the logs and surface to user if it happens.
   - **MINIMAL PATH**: confirmed above.
   - **WORKTREE CHECK**: yes (step 4).

   Show the completed checklist and **get user approval before continuing to step 6**.

6. **Implementation — code-side (no prod writes yet).**
   a. Commit the audit script if it's not yet at HEAD: `git add scripts/audit_residual_chart_facts.py`.
   b. Generate the filing-ids file:
      ```bash
      set -a && source .env && set +a
      psql "$DATABASE_URL" -A -t -F$'\n' -c \
        "SELECT DISTINCT doc_id FROM v2_metric_facts WHERE source_type='chart' ORDER BY doc_id" \
        > /tmp/legacy_097_filing_ids.txt
      wc -l /tmp/legacy_097_filing_ids.txt        # expect 10
      cat /tmp/legacy_097_filing_ids.txt
      ```
      Do NOT commit this file (it's run-time scratch). Confirm count == 10 and IDs match the audit output.
   c. Optionally add a one-paragraph note under `docs/operations/` describing the residual-chart-fact drain procedure (so a future operator can repeat it). Keep it short.

7. **PROD BACKFILL — STOP FOR EXPLICIT USER APPROVAL.**

   Print the exact command you intend to run, including:
   - The `CHART_BUDGET_PER_FILING_USD` value chosen
   - The 10 filing IDs
   - The expected outcome (28 decisions destroyed, ~100–130 chart images gain `detected_metrics`, ~$2–$5 spend)
   - The fact that there is no rollback for the 28 decisions

   Then ask: `"This is a prod-destructive operation. Confirm 'yes, run the backfill' to proceed."`

   Do NOT proceed on ambiguous input. Per global `CLAUDE.md`:
   > "Never interpret ambiguous input as approval for destructive git operations."
   The same rule applies here even though this is a script run rather than a git op — the prod-destruction reversibility is the same shape.

   On explicit `yes`:
   ```bash
   set -a && source .env && set +a
   FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \
   CHART_BUDGET_PER_FILING_USD=2.00 \
   python3 scripts/batch_v2_extraction.py \
     --chart-only \
     --force-reextract \
     --filing-ids-file /tmp/legacy_097_filing_ids.txt 2>&1 | tee /tmp/legacy_097_backfill.log
   ```
   Capture the log. Watch for:
   - `force-reextract purging reviewed filing: filing_id=X purged_decision_count=N ... chart_only=True` (expected, ~28 total across filings)
   - `force-reextract hiding reviewed images: ...` (UNEXPECTED — if you see it, stop and surface)
   - `chart_budget_usd=2.0` in any per-filing log line (confirms env override took effect)
   - Per-filing fact_count=0 (correct — chart pipeline emits no per-value facts post-pivot)

8. **Verify the outcome.**
   ```bash
   python3 scripts/audit_residual_chart_facts.py 2>&1 | tee /tmp/legacy_097_postaudit.txt
   ```
   Expected:
   - 0 rows returned (no filings carry residual chart facts) — this is the success state
   - If rows are returned, chart_facts and chart_fact_decisions should be 0; `chart_imgs_with_detected` should be substantially > 0 (target ≥ 100 across the 10 filings, vs 0 before)
   - Run a separate query to verify text-fact decisions preserved:
     ```bash
     psql "$DATABASE_URL" -c "
       SELECT mf.doc_id, COUNT(*) AS text_decs
       FROM v2_review_decisions rd
       JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
       WHERE mf.source_type <> 'chart' AND mf.doc_id IN (SELECT unnest(string_to_array('$(paste -sd, /tmp/legacy_097_filing_ids.txt)', ',')::int[]))
       GROUP BY mf.doc_id ORDER BY mf.doc_id;"
     ```
     Expected: 146 total across 9 filings (PYPL 1753 has 0 text decisions). If lower, something went wrong — DO NOT proceed to fragment closure; surface to user.
   - Verify image-metric confirmations preserved:
     ```bash
     psql "$DATABASE_URL" -c "
       SELECT COUNT(DISTINCT (imc.img_id, COALESCE(imc.detected_metric_id, imc.confirmed_metric_id, ''), imc.reviewer_id))
       FROM v2_image_metric_confirmations imc
       JOIN v2_image_assets ia ON ia.img_id = imc.img_id
       WHERE ia.doc_id = 1753;"
     ```
     Expected: 3. If lower, surface immediately.

9. **Tests (light).** There's no unit test for this operation — it's an operator script run. But the audit script's SQL should be sanity-checked against the local Docker DB if it's running:
   ```bash
   docker compose ps  # check if local Postgres is up
   # If yes:
   DATABASE_URL="$TEST_DATABASE_URL" python3 scripts/audit_residual_chart_facts.py
   # Should run cleanly even if it returns 0 rows (local test DB likely has no chart facts)
   ```
   Run `pytest -x -q --tb=short` on any tests that touch `scripts/` if they exist (`rg -l "audit_residual_chart_facts" tests/` — likely none). Pre-existing failures: per project `CLAUDE.md`, do not spend time fixing predates.

10. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section structured roughly as:
    ```markdown
    ### Resolution

    Drained the 30 residual chart `v2_metric_facts` rows via `chart_only=True --force-reextract` on 2026-04-28 with `CHART_BUDGET_PER_FILING_USD=2.00`.

    **Measured outcome (post-run audit):**
    - Chart facts remaining: 0 (was 30)
    - Chart-fact reviewer decisions destroyed: 28 (intentional; CASCADE via `v2_review_decisions.fact_id ON DELETE CASCADE`)
    - Text-fact reviewer decisions: <N> (was 146; should be unchanged)
    - Image-metric confirmations on PYPL filing 1753: <N> (was 3; should be unchanged)
    - Chart images with `detected_metrics` populated: <N> / 154 (was 0)
    - Vision API spend: ~$<actual>
    - Pipeline runtime: ~<actual> min

    Reviewer follow-up: <N> chart images now surface in the per-(image, metric) review queue across the 10 filings. Estimated reviewer time: ~25 min in bulk-image flow.

    **Why Option 2 was picked over surgical drain:** the surgical-drain path (DELETE chart facts only, no re-extraction) abandons the 28 decisions without producing any new presence signal, since the chart images had `detected_metrics IS NULL` and no fresh classification would be written. Option 2 produces a real reviewable surface.

    See `scripts/audit_residual_chart_facts.py` for the verification mechanism (read-only).
    ```
    Per `feedback_known_issues_pr_refs_int_not_string`, write `- 290`, not `- '#290'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`.

11. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit`. Run from your worktree. The PR contains:
    - `scripts/audit_residual_chart_facts.py` (new)
    - `docs/known-issues/legacy-097-...md` (status flip + Resolution)
    - Optional: brief runbook addition under `docs/operations/`

12. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Modifying `MAX_CHART_CALLS_PER_DOCUMENT`, `DEFAULT_CHART_BUDGET_PER_FILING_USD`, or any per-doc cap as a permanent change. The lift is **runtime-only via env var** for this backfill.
- Changing `chart_only=True` semantics in `src/extraction_v2/persistence.py`. The current behavior is correct; only the warning text "purging image-metric confirmations" is misleading. Do **not** edit it as part of this PR — that's a separate, low-priority cleanup. (If you want to file a follow-up gh-N fragment for it, fine — but don't conflate.)
- Adding tests for `chart_only=True` or the audit script unless an obviously trivial smoke test is at hand.
- Reviewing the chart images yourself in the UI. That's reviewer work for RGM; the PR's job is to make those images surface.
- Concurrent in-flight work — do **not** touch:
  - `src/web/routes/review_unified.py`, `src/web/routes/api_unified.py`, `src/web/templates/unified_review.html` (legacy-089 + open PR #284)
  - `tests/integration/extraction_v2/test_e2e_pipeline.py`, `tests/integration/test_full_page_ocr_pipeline.py`, `src/infra/image_storage.py` (gh-262)
  - `scripts/export_image_training_data.py`, `scripts/retrain_image_triage.py`, `scripts/benchmark_vision.py`, `src/llm/vision_client.py`, `src/gold_standard/image_eval.py` (gh-196)
  - `.claude/commands/commit-proj.md`, `scripts/validate_known_issues_fragments.py` (gh-258)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first; the audit's chart-fact-decision count was already stale (fragment said 18, audit measured 28 — re-run before acting)
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate the backfill execution to a subagent, do **not**. The user-approval gate must be honored synchronously.
- `feedback_destructive_recovery_workflow` — bundle audit+recovery in fix PR, frame around reviewer-decision exposure not abstract risk
- `feedback_run_recovery_before_verification` — do not run the post-audit (step 8) until the backfill (step 7) actually completed cleanly; otherwise the "verification" measures stale state
- `feedback_known_issues_pr_refs_int_not_string` — `- 290`, not `- '#290'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `project_image_review_decisions_for_ml_training` — image review decisions are ML training signal; the 28 chart-fact decisions ARE included in that signal. Their abandonment is deliberate (Option 2 was chosen with this trade-off explicit).
- `project_db_query_vs_execute` — `db.query` is SELECT-only

## Return
The PR URL when done, plus:
- Summary of the backfill log (purged_decision_count, chart_budget_usd, chart_call counts)
- Post-audit numbers (text-fact decisions preserved, image confirmations preserved, detected_metrics populated count)
- One-line note for RGM on the reviewer follow-up: "<N> chart images now surface in the image queue across <N> filings; estimated review time ~<N> min."

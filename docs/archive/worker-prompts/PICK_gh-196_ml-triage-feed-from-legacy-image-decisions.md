You are working gh-196: ML image-triage training pipeline reads legacy `v2_image_review_decisions`.

## Source of truth
- Fragment: `docs/known-issues/gh-196-ml-triage-feed-from-legacy-image-decisions.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Related context (read for shape, do not modify unless implementation requires): `scripts/export_image_training_data.py` (already UNIONs both surfaces — done in this fragment's first slice), `scripts/retrain_image_triage.py`, `scripts/benchmark_vision.py`, `src/llm/vision_client.py`, `src/gold_standard/image_eval.py`, the `v2_image_metric_confirmations` schema (in `sql/`), and `CLAUDE.md` design principle 4 (chart-presence pivot semantics).

## Status note (read first)
The fragment is **`partially-resolved`**. `pr_refs: [197]` is **wrong** — PR #197 was an unrelated SQL-migration scheme change. The actual partial-resolution PR is whichever shipped the `scripts/export_image_training_data.py` UNION (the fragment's "Resolution status (this PR)" section). **Do not** assume PR 197 is the in-scope precedent.

The remaining work (per fragment "Still open"):
1. Port `scripts/benchmark_vision.py` off the legacy `v2_image_review_decisions`-only corpus query.
2. Decide whether `chart_type` is captured in `v2_image_metric_confirmations` (schema change) or stratification is reworked without it.
3. Make sure the triage model retraining path (`scripts/retrain_image_triage.py`) handles `chart_type=NULL` gracefully when confirmation-derived rows dominate.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Verify the partial-resolution claim:
   ```bash
   git fetch origin main --quiet
   grep -nE "v2_image_metric_confirmations|v2_image_review_decisions" scripts/export_image_training_data.py scripts/retrain_image_triage.py scripts/benchmark_vision.py
   ```
   Expected: `export_image_training_data.py` references both tables; `benchmark_vision.py` references only `v2_image_review_decisions`. If `benchmark_vision.py` already references confirmations, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Also confirm the `pr_refs: [197]` is stale (PR 197 unrelated to this fragment) — if so, plan to fix the `pr_refs` as part of your closure PR. Don't repurpose 197.

2. **Plan mode.** Use plan mode — this touches schema decisions and ML training code. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by global `Planning Rules`. Specifically:
   - If you take the schema-extension path (capture `chart_type` in confirmations), document the new column in `.claude/rules/sql.md` migration notes and any analytics-view docs that join `v2_image_metric_confirmations`.
   - If you take the stratification-rework path, document the rationale where the bake-off harness lives.

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-196-benchmark-vision-confirmations-port`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:** confirm `v2_image_metric_confirmations` does **not** capture `chart_type` (read the migration that created it — likely under `sql/4*_create_v2_image_metric_confirmations.sql` or a timestamp-named migration). Confirm `v2_image_review_decisions` is the legacy table and **not** still being written by any current code path (per `project_image_review_decisions_for_ml_training`, those rows are ML training signal — preserve, don't drop).
   - **SCOPE CHECK:** the fragment's "Still open" list contains a **product decision** (capture `chart_type` vs. accept feature loss). **Surface this decision to the user before writing code.** If the user defers, ship only the lowest-risk slice (e.g., a `benchmark_vision.py` UNION read that emits `chart_type=NULL` for confirmation-derived rows and excludes them from chart-type stratification with a logged warning).
   - **RULES COMPLIANCE:** `project_image_metric_confirmations_distinct_aggregation` — `v2_image_metric_confirmations` is keyed per-(img, reviewer, metric); naive `COUNT(*)` double-counts. Any aggregation in the new query path must `DISTINCT` on `img_id`. Re-derive image-level relevance the same way `export_image_training_data.py` already does:
     - `relevant`     = ANY confirmation in `{accept, correct, add}`
     - `not_relevant` = at least one confirmation, all rejects
     - excluded       = only `skip` confirmations, or zero confirmations
     Match that aggregation exactly so the two scripts produce consistent corpora.
   - **RISK ASSESSMENT:** legacy rows must continue to take precedence when the same `img_id` appears in both surfaces (the existing precedent in `export_image_training_data.py`). Diverging from that rule will produce silent label flips between old and new surfaces. Test for this with a fixture row that exists in both tables with different labels.
   - **MINIMAL PATH:** the smallest viable ship is the `benchmark_vision.py` UNION port + a `chart_type=NULL` handling note in `retrain_image_triage.py`. Defer schema extensions unless the user explicitly approves.

5. **Implementation** (assuming the conservative minimal path):
   - Port `scripts/benchmark_vision.py`'s corpus query to UNION `v2_image_metric_confirmations` rows alongside `v2_image_review_decisions`, mirroring the aggregation rules from `export_image_training_data.py`.
   - For `chart_type` stratification: confirmation-derived rows emit `chart_type=NULL`. Decide explicitly per fragment: either (a) exclude them from chart-type strata with a logged warning, or (b) bucket them into an `unknown` stratum. Document the choice in a one-line comment.
   - In `scripts/retrain_image_triage.py`, confirm the model-input pipeline handles `chart_type=NULL` (treat as missing feature). If it currently crashes on NULL, add the smallest fix to make it robust.
   - Optional: a small smoke-test fixture in `tests/integration/scripts/` (or wherever existing script tests live) that runs a degenerate corpus through `benchmark_vision.py` end-to-end. Don't expand into a full bake-off harness rewrite.

6. **Tests.**
   - Run any existing tests for the touched scripts: `pytest tests/integration/scripts -x -q --tb=short` (or wherever they live — `rg -l "benchmark_vision\|export_image_training_data\|retrain_image_triage" tests/`).
   - Add a unit test for the new UNION corpus aggregation: a fixture with one legacy-only row, one confirmation-only row, and one row in both, asserting legacy wins precedence and confirmation aggregation matches the documented rules.
   - Pre-existing failures: per project `CLAUDE.md`, do not spend time fixing failures that predate this work.

7. **Update fragment status as part of the same PR.** Flip `status: partially-resolved` → `resolved` (or keep `partially-resolved` if you only ship the `benchmark_vision.py` port and defer the `chart_type` decision — note the deferred work in `note:`). **Fix the stale `pr_refs`**: replace `pr_refs: [197]` with the actual partial-resolution PR # (find it via `git log --all --oneline -- scripts/export_image_training_data.py | head -5`) plus your new PR #. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 286`, not `- '#286'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`. Append a `### Resolution` section describing what shipped and what (if anything) remains.

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit`. Run it from your worktree.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- The `chart_type` schema-extension path on `v2_image_metric_confirmations` unless the user explicitly approves it (it is a stakeholder decision, not an autonomous fix).
- A full rewrite of the bake-off harness or the triage model's training loop.
- The "image-level rejection signal for ML training" gap described in **gh-280** (zero-detected-metric "Reject all" leaves no per-metric row). Different code path, separate fragment, separate fix — note it as adjacent only.
- Any UI-side image review work (`src/web/routes/review_unified.py`, `src/web/routes/api_unified.py`, `src/web/templates/unified_review.html`) — that is legacy-089 (in flight) and PR #284. **Do not touch.**
- `tests/integration/extraction_v2/test_e2e_pipeline.py`, `tests/integration/test_full_page_ocr_pipeline.py`, `src/infra/image_storage.py` — gh-262 territory (in parallel). **Do not touch.**
- `.claude/commands/commit-proj.md`, `scripts/validate_known_issues_fragments.py` — gh-258 territory (in parallel). **Do not touch.**

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first; pr_refs: [197] is known to be stale here
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — `- 286`, not `- '#286'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `project_image_review_decisions_for_ml_training` — image review decisions ARE the ML training signal; preserve the per-(image, metric) decision trail
- `project_image_metric_confirmations_distinct_aggregation` — `v2_image_metric_confirmations` rollups need DISTINCT on `img_id`; naive `COUNT(*)` double-counts
- `project_db_query_vs_execute` — `db.query` is SELECT-only; use `db.execute` for INSERT/UPDATE/DELETE without RETURNING

## Return
The PR URL when done.

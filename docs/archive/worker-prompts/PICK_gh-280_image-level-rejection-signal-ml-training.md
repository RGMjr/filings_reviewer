You are working gh-280: Image-level rejection signal for ML training. **Read the full prompt before starting** — this is a verify-then-decide task, not a feature build.

## Source of truth
- Fragment: `docs/known-issues/gh-280-image-level-rejection-signal-ml-training.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate. Note especially the design principle 4 paragraph that documents the existing sentinel-row behavior for "Reject all (no relevant metrics)".
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Why this prompt is different

Spot-check before /pick-issues drafted this: `src/web/routes/api_unified.py:672` already contains the branch `if not detected_metric_id and rejection_reason != "no_relevant_metrics":` and `src/infra/db.py:2234` has a comment referencing "the NULL/NULL 'no relevant metrics' sentinel reject". CLAUDE.md (Core Design Principles §4) describes this behavior as already shipped: a sentinel `v2_image_metric_confirmations` row with NULL `detected_metric_id` and NULL `confirmed_metric_id` is written when "Reject all" is pressed on a zero-detected-metric image.

So the fragment's stated gap ("zero-detected-metric images leave no row") **looks already-resolved**. The work is to confirm that, then either:
- **Path A (most likely):** Produce a fragment-only closure PR — flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]` after creation, append a `### Resolution` section pointing to the resolving commit (find via `git log -S 'no_relevant_metrics' src/web/routes/api_unified.py`), and close GH issue #280 with a note. Per `project_fragment_only_closure_pattern` and `feedback_investigate_then_fix_under_30min` and `feedback_shipped_not_effective`.
- **Path B (fallback):** If reproduction shows the sentinel row is **NOT actually written** end-to-end (e.g. the branch in `api_unified.py:672` is reachable but the upstream caller never enters it for the zero-detected case), implement the missing piece per the fragment's "Next Steps".

Do not skip the verification step. `feedback_verify_issue_status` and `feedback_fragment_fix_is_hypothesis` apply directly here.

## Workflow
1. **Reproduce the claimed gap.** Without making any code changes:
   - Find a `v2_image_assets` row with no detected_metrics (`SELECT img_id FROM v2_image_assets WHERE detected_metrics IS NULL OR detected_metrics = '[]' LIMIT 5;`). Use a dev DB, not prod.
   - Trace the "Reject all (no relevant metrics)" code path in `src/web/static/js/review_images_v2.js` (search for the button handler) → the API endpoint it calls in `src/web/routes/api_unified.py` → the DB write. Confirm whether a `v2_image_metric_confirmations` row is written for the zero-detected case.
   - If you can run a local server, exercise the button against a zero-detected image and `SELECT * FROM v2_image_metric_confirmations WHERE img_id = <that one>` to confirm. If you cannot run a local server, trace the code path carefully and document the sentinel-row INSERT site explicitly.
   - Record findings in the plan: file:line of the INSERT, file:line of the call site, conditions under which the row is or isn't written.
2. **Decide Path A vs Path B.** If the sentinel row is written for zero-detected "Reject all" presses (matching CLAUDE.md §4), you are on **Path A**. Otherwise **Path B**. Surface the decision to the user before implementing.

### Path A — fragment-only closure
3A. **Worktree-first.** `EnterWorktree fix/gh-280-fragment-closure-stale`.
4A. Edit `docs/known-issues/gh-280-image-level-rejection-signal-ml-training.md`:
    - `status: open` → `status: resolved`
    - `autonomy: skip` → `autonomy: n/a`
    - Add `pr_refs: [<this PR #>]` after PR creation (write `- <int>`, never `- '#<int>'` per `feedback_known_issues_pr_refs_int_not_string`)
    - Append a `### Resolution` section explaining: discovered already-fixed during /pick-issues triage; cite the resolving commit (`git log -S 'no_relevant_metrics' src/web/routes/api_unified.py` should narrow it) and CLAUDE.md §4 as the authoritative description.
    - Do **not** add any frontmatter fields outside the validator allowlist (`pr_refs`, `gh_issue`, `note`) per `feedback_known_issues_validator_optional_fields`.
5A. Commit + PR via `/commit-proj`. Pre-existing test failures are acceptable to ignore on a docs-only PR per CLAUDE.md "Testing Standards" (docs-only commits may skip lint and tests).
6A. After merge, close GH issue #280 with a comment referencing the resolving commit and this closure PR.
7A. Verify auto-merge per `feedback_verify_auto_merge_after_commit`.

### Path B — implement the missing signal
3B. **Plan mode** required. Decide between fragment options (a) `decision='reject_image'` enum value or (b) splitting `review_status='skipped'` into `skipped_rejected` / `skipped_parked`. Surface tradeoffs to the user. Do not pick unilaterally — this is a schema change either way.
4B. **Worktree-first.** `EnterWorktree fix/gh-280-image-level-rejection-signal`.
5B. **Pre-Implementation Gate** with full ASSUMPTION AUDIT — the fragment is recent (2026-04-28) but the codebase moves fast around image confirmations (PR #284 shipped "Reject all" recently, and `claude/feat-gh-293-reopen-reviewed-image` is currently in flight on `api_unified.py`). Verify every assumption. Risk row must explicitly check the in-flight gh-293 worktree's diff against `api_unified.py` to avoid merge-conflict-by-implementation.
6B. Implement. Add a migration if schema changes; update the "Reject all" handler; update the fragment status as part of the same PR per `project_fragment_only_closure_pattern`.
7B. Tests: `pytest -x -q --tb=short`. Add unit coverage for the new signal path.
8B. Commit + PR via `/commit-proj`. Verify auto-merge.

## Out of scope (do NOT expand into)
- Do **not** backfill historical `v2_image_assets.review_status='skipped'` rows. The fragment mentions backfill as optional/future ("Plan backfill for historical skipped rows where intent is recoverable") — skip it. If backfill matters, file a follow-up fragment.
- Do **not** modify the ML triage training pipeline or anything in `scripts/export_image_training_data.py` / `scripts/retrain_image_triage.py` / `scripts/benchmark_vision.py` — those are gh-196's scope (still partially-resolved).
- Do **not** redesign the per-metric confirmation schema or rename fields.
- Do **not** edit `src/web/templates/unified_review.html` or `src/web/static/js/review_images_v2.js` while gh-293 and gh-294 worktrees are locked on them.
- Do **not** touch chart/image classifier scoring (`src/extraction_v2/chart/*`) — that's gh-289's scope.

## Memory references that apply
- `feedback_verify_issue_status` — known-issue fragments go stale; check git/code state before recommending action **(critical for this prompt)**
- `feedback_fragment_fix_is_hypothesis` — reproduce and rule out the proposed cause before implementing the proposed fix
- `feedback_investigate_then_fix_under_30min` — if diagnosis+fix is faster than writing a thorough fragment, do the work now; especially relevant for documented-but-broken safety controls
- `feedback_shipped_not_effective` — closure ≠ outcome; verify upstream preconditions are met before believing an issue is solved
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_pr_refs_int_not_string` — `pr_refs` must be a list of ints
- `feedback_known_issues_validator_optional_fields` — frontmatter optional fields are limited to `pr_refs`, `gh_issue`, `note` (CI Lint enforces; local pre-commit doesn't catch)
- `feedback_close_partially_resolved_cleanly` — close cleanly; don't leave indefinitely partially-resolved
- `project_image_review_decisions_for_ml_training` — preserve per-(image, metric) decision trail; the sentinel design exists precisely to fill the zero-detected-metric gap
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after PR opens
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree

## Return
The PR URL when done. State explicitly which path (A or B) you took, and which commit resolves the original gap.

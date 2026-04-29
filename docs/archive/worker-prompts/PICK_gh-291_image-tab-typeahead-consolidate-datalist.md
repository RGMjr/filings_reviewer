You are working gh-291: Drop redundant `/api/v2/metrics/list` AJAX from image-tab typeahead (consolidate datalist).

## Source of truth
- Fragment: `docs/known-issues/gh-291-image-tab-typeahead-consolidate-datalist.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm the duplicate datalist still exists by grepping for `detected-metrics-datalist` in `src/web/templates/unified_review.html` and `src/web/static/js/review_images_v2.js`. As of session start, the inputs at `unified_review.html:973` and `:991` still bind `list="detected-metrics-datalist"`, the empty datalist still lives at `:1007`, and `loadMetricsList()` / `DATALIST_ID` / `populateDatalist()` still exist in `review_images_v2.js:297,337,369,386`. If the consolidation has already shipped, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Wait-or-coordinate check.** Two locked worktrees touch the same two UI files: `claude/feat-gh-293-reopen-reviewed-image` and `claude/feat-gh-294-image-tab-shortcuts`. Before starting, run `gh pr list --search 'gh-293 OR gh-294' --state all --json number,state,headRefName` and verify both have either merged to `main` or have no in-progress edits to `unified_review.html` lines around the image-tab inputs (~970–1010) and to `review_images_v2.js` `init()` / `state.metricsList`. If either is still in flight, **stop and report** — do not race them. Per `feedback_subagent_midstream_stops` and the skill's parallel-safety rule, the right move is to wait for them to merge then rebase.
3. **Plan mode.** Use plan mode for this change. Run `/plan-review` before exiting plan mode. The change is mechanical but touches a hot UI file — a plan is still warranted because of the in-flight collision risk.
4. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-291-image-tab-datalist-consolidation`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
5. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code. Pay special attention to the Risk Assessment row: `loadMetricsList()` may be called from anywhere in `review_images_v2.js` — grep for all references before deleting.
6. **Implement.** Per the fragment "Next Steps":
   - `unified_review.html`: switch `list="detected-metrics-datalist"` → `list="all-metrics-datalist"` on the two image-tab inputs (`add-missed-detected-input` ~line 973, `metric-correct-input` ~line 991). Delete the empty `<datalist id="detected-metrics-datalist">` element (~line 1007).
   - `review_images_v2.js`: remove `DATALIST_ID` (line 297), the `loadMetricsList()` call from `init()` (line 337), the `loadMetricsList()` definition (lines 369–390 area), the unused `populateDatalist()` helper, and any `state.metricsList` assignment.
   - **Leave `/api/v2/metrics/list` route in place** — referenced by integration / UI tests (per fragment).
7. **Tests.** Per project CLAUDE.md testing standards — `pytest -x -q --tb=short`. Plus run the UI suite: `cd tests/ui && npx playwright test review.spec.js` (or the project's documented command). The image-tab typeahead behavior is exercised by Playwright; both inputs should still resolve metric IDs against the datalist.
8. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: n/a`, set `pr_refs: [<this PR #>]` (after PR creation), append a short `### Resolution` section. Per `project_fragment_only_closure_pattern` and `feedback_known_issues_pr_refs_int_not_string` (write `- 291`, not `- '#291'`).
9. **Commit + PR.** Use the **project-local** `/commit-proj` skill.
10. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

## Out of scope (do NOT expand into)
- Do **not** delete or modify the `/api/v2/metrics/list` Flask route (`src/web/routes/api_unified.py`) — integration / UI tests still hit it.
- Do **not** modify the text-tab `<datalist id="all-metrics-datalist">` block (~line 1505) — it's the canonical server-rendered datalist this PR is consolidating onto.
- Do **not** rebind any keyboard shortcuts or buttons on the image tab — that's gh-294's scope, currently in flight on `claude/feat-gh-294-image-tab-shortcuts`.
- Do **not** add an "Undo review" affordance — that's gh-293's scope, currently in flight on `claude/feat-gh-293-reopen-reviewed-image`.
- Do **not** touch any chart/image classifier code, OCR, or extraction stages.

## Memory references that apply
- `feedback_verify_issue_status` — verify on `origin/main` and grep current code first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after PR opens
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_pr_refs_int_not_string` — `pr_refs` must be a list of ints
- `project_web_route_doc_authority` — if behavior docs need updating, the canonical surface is `.claude/rules/web.md`, not `HUMAN_REVIEW_SYSTEM.md`

## Return
The PR URL when done.

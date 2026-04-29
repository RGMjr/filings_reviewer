You are working legacy-091: gemini-pro Returns Empty Content on vision + response_format=json_object.

## Source of truth
- Fragment: `docs/known-issues/legacy-091-gemini-pro-empty-content-on-vision-json-object.md` (read in full from origin/main before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Reference doc: `docs/operations/vision-bakeoff-metric-classify-2026-04-23.md` (the bake-off where this was discovered)

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Inspect `src/llm/vision_client.py` and `scripts/benchmark_vision.py` for changes since `updated: 2026-04-23`. Re-run a minimal repro: one image + `gemini-pro` (`gemini-2.5-pro`) via `VisionClient.analyze_image(..., response_format={"type": "json_object"})` and confirm the empty-`content` behavior still reproduces. If already fixed, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Plan mode.** Use plan mode for any non-trivial change. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by the global `Planning Rules`.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-091-gemini-pro-json-mode`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global `CLAUDE.md`). Show the completed checklist and get user approval before writing code. This change touches `src/llm/vision_client.py` (provider adapter) — pay attention to ASSUMPTION AUDIT (which Gemini SDK version is pinned, which other callers depend on the JSON-mode hint) and RISK ASSESSMENT (does dropping JSON-mode affect non-vision Gemini callers?).
5. **Implementation strategy** (from fragment Next Steps; pick after the gate, do not pre-decide):
   - Either drop the `response_format={"type": "json_object"}` hint on the Gemini Pro vision path and parse free-text back into the four-field classify schema, or
   - Route Pro through a non-JSON code path when `analyze_image` is the caller, leaving non-vision Gemini callers' JSON-mode intact.
   - Until resolved, the fragment also calls for omitting `gemini-pro` from `BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY` — only do this if you cannot fix in code in this PR.
6. **Tests.** Per project `CLAUDE.md` testing standards: `pytest -x -q --tb=short`. Add a unit test that exercises the Gemini Pro vision JSON path (mocked SDK response is fine) so this can't regress silently. Don't skip on failures.
7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: n/a` (already), set `pr_refs: [<this PR #>]` (added after PR creation), and append a `### Resolution` section describing what changed and why. Per `project_fragment_only_closure_pattern`. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 261` not `- '#261'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}` when closing.
8. **Commit + PR.** Use the **project-local** `/commit` skill (Safe Commit + PR Skill). Per `feedback_commit_skill_name_collision`, the global skill may load instead — if you see "Safe Commit Skill" without a PR step, follow up manually with `gh pr create` + `gh pr merge --auto --squash`.
9. **Verify auto-merge.** After `/commit` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`. Note: the project-local `/commit` may rename the branch to `fix/legacy-091-...` — fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push (per `feedback_commit_skill_renames_pr_branch`).

## Out of scope (do NOT expand into)
- Other Gemini quirks beyond the empty-content-on-JSON-vision bug.
- Refactoring `VisionClient` provider abstractions.
- Vision bake-off methodology changes (`docs/operations/vision-bakeoff-*`).
- Touching the metric-classify pipeline outside the provider adapter.
- Concurrent worktree footprints: `docs/known-issues/`, `tests/integration/test_db_filings_reviewers.py`, `tests/integration/extraction_v2/`, `sql/` — left to legacy-113 and legacy-116 picks.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_commit_skill_name_collision` — global vs project-local /commit
- `feedback_commit_skill_renames_pr_branch` — fetch headRefName before follow-up pushes
- `feedback_known_issues_pr_refs_int_not_string` — `- 261`, not `- '#261'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR

## Return
The PR URL when done.

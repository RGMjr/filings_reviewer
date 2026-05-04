You are working gh-294: Image tab — keyboard-shortcut audit + parity with text tab.

## Source of truth
- Fragment: `docs/known-issues/gh-294-image-tab-keyboard-shortcut-audit.md` (read in full before planning)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (`~/.claude/CLAUDE.md`) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Authoritative web-route / API contract doc is `.claude/rules/web.md` — per `project_web_route_doc_authority`. The fragment calls for documenting the final mapping there.

## Critical pre-step: existing in-flight work
There is a **locked worktree** at `.claude/worktrees/agent-a0011517da25e5304` on branch `claude/feat-gh-294-image-tab-shortcuts` containing one unmerged commit:

    809186e feat(review-ui): image-tab keyboard shortcut audit + parity with text tab (Closes #294)

No open PR exists for it (gh pr list shows none). Before doing anything else:

1. Inspect that commit: `git show 809186e --stat` and `git diff origin/main..claude/feat-gh-294-image-tab-shortcuts`.
2. Decide:
   - **If the commit is good and complete:** unlock + adopt that worktree (or `EnterWorktree` onto that branch), rebase on `origin/main`, run tests, push and open a PR via `/commit-proj` (which will detect the existing branch). This is the preferred path — don't re-do work.
   - **If the commit is partial or stale:** report the gap to the user before continuing. Do not silently overwrite or abandon another session's work.
3. If the worktree appears truly stranded (locked but no recent activity), surface that to the user and ask whether to adopt or restart from a fresh worktree `fix/gh-294-image-tab-shortcuts`.

## Workflow (after the pre-step decision)
1. **Verify the issue is still relevant.** Re-read the fragment from origin/main. Tabulate the current shortcuts in `src/web/templates/unified_review.html` (text tab) vs `src/web/static/js/review_images_v2.js` (image tab) at HEAD. Note specifically whether the "Reject all (no relevant metrics)" button (PR #284) has a binding.
2. **Plan mode.** Plan must cover:
   - The full audit table (existing keys, both tabs, semantics).
   - Policy for destructive/bulk actions (chord vs single-letter). The fragment recommends chord (e.g. Shift+R) for "Reject all" — justify or reject this in the plan.
   - The proposed final key mapping (aligned across tabs where semantics overlap: prev/next/next-filing).
   - Documentation update in `.claude/rules/web.md`.
   - Manual UI verification plan (per global CLAUDE.md "For UI or frontend changes" — start the dev server and exercise each shortcut in a browser; do not rely solely on automated tests).
   Run `/plan-review` before exiting plan mode.
3. **Worktree-first.** Either adopt the existing locked worktree (preferred if usable) or `EnterWorktree fix/gh-294-image-tab-shortcuts`.
4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code.
5. **Tests.** `pytest -x -q --tb=short` for any JS-adjacent Python tests. Run the dev server and exercise each shortcut in the browser — type checking does not verify UX.
6. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: skip` → `n/a`, set `pr_refs: [<this PR #>]`, and append a `### Resolution` section. Per `project_fragment_only_closure_pattern`. Per `feedback_known_issues_validator_optional_fields`, only `pr_refs`/`gh_issue`/`note` are allowed in frontmatter.
7. **Commit + PR.** Use the project-local `/commit-proj` skill.
8. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`.

## Out of scope (do NOT expand into)
- Adding new review buttons / actions — only wiring shortcuts to existing buttons.
- Refactoring `review_images_v2.js` beyond the shortcut surface.
- Touching files in concurrent worktrees: anything in `src/infra/db.py` or `tests/integration/**` (gh-328 worker), or `src/extraction_v2/chart/**` (gh-289 worker).

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `project_web_route_doc_authority` — `.claude/rules/web.md` is authoritative; HUMAN_REVIEW_SYSTEM.md is overview only
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_validator_optional_fields` — only `pr_refs`, `gh_issue`, `note` allowed when closing
- `feedback_known_issues_pr_refs_int_not_string` — write `- 327`, not `- '#327'`
- `feedback_subagent_midstream_stops` — if you delegate, dispatch a tightly-scoped wrap-up pinned to the worktree if returns are truncated

## Return
The PR URL when done.

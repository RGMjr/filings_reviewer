You are working legacy-075: Implement the deferred image-queue variant of the cross-filing auto-advance Playwright E2E test (text-queue variant landed in PR #178; image-queue variant remains).

## Source of truth
- Fragment: `docs/known-issues/legacy-075-missing-playwright-e2e-for-cross-filing-auto-advance.md` (read in full from `origin/main` before planning). Status is `partially-resolved` — only the image-queue variant remains.
- `CLAUDE.md` (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm the deferred stub still exists at `tests/ui/review.spec.js:1137` (currently a comment block: `// Image-queue completion variant deferred — the images tab's init JS fires an...`). Confirm PR #178's text-queue test ("text-queue completion navigates to next filing") is in `tests/ui/review.spec.js` as the model to mirror. Confirm `tests/ui/test_server.py` does NOT already handle `/api/v2/image-confirmation/*` (or whichever endpoints the image tab posts to). If the image-queue variant has already shipped, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Reproduce the gap once before planning.** Run the text-queue test and observe its shape (`cd tests/ui && npx playwright test review.spec.js -g "text-queue completion"` — adjust grep to project convention). Read the test source so the image variant mirrors structure exactly — same setup, same assertion style, same fixtures.
3. **Plan mode.** Use plan mode. Run `/plan-review` before exiting. The plan must include:
   - the seed strategy (two filings, last image of filing A having pending confirmations);
   - the precise sequence of clicks/XHRs the test will assert (relevant → non-relevant → skip per fragment text — verify this matches the actual button labels in `unified_review.html` rather than trusting the fragment verbatim);
   - the stub-server XHR catch-all extension in `tests/ui/test_server.py` (which exact endpoints, what JSON each returns);
   - assertion that the browser lands on filing B with sort order preserved.
4. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-075-image-queue-e2e`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
5. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code. Verify the listed `touches:` paths still exist; check whether any in-flight worktree is editing `tests/ui/test_server.py` (`git worktree list` + scan `.claude/worktrees/*/tests/ui/test_server.py`).
6. **Implement.**
   - Add the new Playwright test in `tests/ui/review.spec.js`, replacing the `// Image-queue completion variant deferred` stub at line ~1137.
   - Extend the stub-server XHR catch-all in `tests/ui/test_server.py` to handle the image-confirmation endpoints the test exercises. Mirror the response shape produced by the real handlers in `src/web/routes/api_unified.py` (read them — don't fabricate). Per `project_web_route_doc_authority`, `.claude/rules/web.md` is the API contract surface; cross-reference if shapes are unclear.
   - Keep the test deterministic — no real DB, no real network.
7. **Tests.** Run the new test in isolation first (`npx playwright test review.spec.js -g "image-queue completion"`), then the full UI suite, then `pytest -x -q --tb=short` (to make sure nothing in the stub-server change broke unit tests that import `tests/ui/test_server.py`).
8. **Update fragment status as part of the same PR.** Flip `status: partially-resolved` → `resolved`, `autonomy: n/a`, append the new PR to `pr_refs` (keep `- 178` and add `- <new>`), append a `### Resolution (image-queue variant)` section. Per `project_fragment_only_closure_pattern` and `feedback_known_issues_pr_refs_int_not_string` (ints, not strings).
9. **Commit + PR.** Use the **project-local** `/commit-proj` skill.
10. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

## Out of scope (do NOT expand into)
- Do **not** modify the text-queue test or its server stubs — PR #178 already covers that path.
- Do **not** modify any production route handler in `src/web/routes/`. This PR is test-only.
- Do **not** modify `unified_review.html` or `review_images_v2.js` — the in-flight worktrees `claude/feat-gh-293-reopen-reviewed-image` and `claude/feat-gh-294-image-tab-shortcuts` own those files right now. The test should target the **current** committed behavior on `main`, not anticipated behavior from those PRs.
- Do **not** add new Playwright fixtures beyond what the image-queue completion test needs. Do not refactor existing fixtures.
- Do **not** add database integration tests — the fragment scope is browser-layer Playwright only.

## Memory references that apply
- `feedback_verify_issue_status` — verify on `origin/main` and grep current code first; `partially-resolved` fragments especially drift fast
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after PR opens
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_pr_refs_int_not_string` — `pr_refs` must be a list of ints
- `project_web_route_doc_authority` — `.claude/rules/web.md` is the canonical web/API contract doc; consult it for endpoint shapes if needed
- `project_image_review_status_not_flipped_by_per_metric` — relevant if the test simulates the per-metric → image-level transition; chain `/skip` to flip `review_status` (no trigger)

## Return
The PR URL when done.

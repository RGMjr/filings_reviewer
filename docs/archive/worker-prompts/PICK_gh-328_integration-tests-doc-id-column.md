You are working gh-328: Integration tests broken by doc_id column removal from v2_metric_facts.

## Source of truth
- Fragment: `docs/known-issues/gh-328-integration-tests-doc-id-column.md` (read in full before planning)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (`~/.claude/CLAUDE.md`) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Likely-relevant context: PR #326 just merged the `doc_id` → `filing_id` rename in `v2_metric_facts` (legacy-038). This fragment captures the residual integration-test fallout.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from origin/main, run a representative failing integration test (e.g. `pytest tests/integration/extraction_v2/test_persistence.py -x -q --tb=short`) to confirm the `column "doc_id" does not exist` symptom still reproduces. Identify the rename migration in `sql/` (likely `sql/202604282225_rename_v2_metric_facts_doc_id_to_filing_id.sql`).
2. **Plan mode.** Use plan mode for this change. Identify every reference to `v2_metric_facts.doc_id` in `src/infra/db.py`, test SQL, and fixtures. Decide whether to update call sites to `filing_id` or to introduce a transitional alias — read the migration's intent before choosing. Run `/plan-review` before exiting plan mode.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-328-integration-tests-doc-id`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code.
5. **Tests.** `pytest tests/integration -x -q --tb=short` must pass. Don't skip on failures. Per `feedback_run_recovery_before_verification` — if you see lingering schema-drift errors, run the documented test-DB recovery (drop+recreate test DB, re-run migrations) before debugging code.
6. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: skip` → `n/a`, set `pr_refs: [<this PR #>]`, and append a `### Resolution` section. Per `project_fragment_only_closure_pattern`. Per `feedback_known_issues_validator_optional_fields`, do NOT add new frontmatter fields.
7. **Commit + PR.** Use the project-local `/commit-proj` skill.
8. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`.

## Out of scope (do NOT expand into)
- Schema changes beyond fixing `doc_id`/`filing_id` references — the column rename already shipped in PR #326.
- Refactoring unrelated `db.py` helpers.
- Touching files in concurrent worktrees: anything under `src/extraction_v2/chart/` (gh-289 worker), `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js`, or `.claude/rules/web.md` (gh-294 worker).

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_run_recovery_before_verification` — schema drift in test DB needs dropdb+migrate, not pytest debugging
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_known_issues_validator_optional_fields` — only `pr_refs`, `gh_issue`, `note` allowed when closing
- `feedback_known_issues_pr_refs_int_not_string` — write `- 327`, not `- '#327'`
- `feedback_subagent_midstream_stops` — if you delegate, dispatch a tightly-scoped wrap-up pinned to the worktree if returns are truncated

## Return
The PR URL when done.

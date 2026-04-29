You are working legacy-113: `test_db_filings_reviewers.py::test_reviewers_aggregates_text_and_image_sources` fails on missing `v2_documents` relation.

## Source of truth
- Fragment: `docs/known-issues/legacy-113-test-db-filings-reviewers-v2-documents-missing.md` (read in full from origin/main before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- Related fragments to cross-reference: `docs/known-issues/legacy-110-*` (migration registry drift — likely shared root cause), `docs/known-issues/legacy-114-*` (recently-resolved checksum self-heal context, PR #254/#255).

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm the failure still reproduces on clean main:
   ```
   pytest tests/integration/test_db_filings_reviewers.py::TestReviewerAggregation::test_reviewers_aggregates_text_and_image_sources -x -q
   ```
   If it now passes (e.g. legacy-110 was fixed in a way that incidentally fixed this), abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`. Per `feedback_run_recovery_before_verification`: if the test DB looks corrupted, run the documented recovery (e.g. `dropdb` per the integration test runbook) before assuming the test itself is wrong.
2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by the global `Planning Rules`.
3. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-113-test-db-filings-reviewers-missing-v2-documents`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global `CLAUDE.md`). The fragment lists `touches: sql/` which is a wide glob — narrow the **MINIMAL PATH** to the specific files actually needed (likely `tests/integration/conftest.py`'s `_apply_migrations_to_test_db` and possibly a single migration registration), and rule out broad `sql/` edits unless required. ASSUMPTION AUDIT must verify the current registry order and the per-worker DB isolation behavior in `tests/integration/conftest.py::_isolate_xdist_worker_database`.
5. **Diagnostics first** (per fragment Next Steps):
   - Run the integration conftest migration step manually and confirm whether `v2_documents` is created (`\dt v2_*` in `psql`).
   - Cross-reference with legacy-110 (migration registry drift). If that's the underlying bug, fix in the registry rather than papering over here.
   - Last-resort fallback (only if registry fix is out of scope): make the test skip when V2 schema is absent, with a clear xfail/skip reason linked to the upstream fragment.
6. **Tests.** `pytest -x -q --tb=short`. The single failing test must pass. Per project `CLAUDE.md` testing standards, run the full integration test file at minimum to ensure no other regressions. Don't skip on failures.
7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, and append a `### Resolution` section describing the root cause and fix. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 261` not `- '#261'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}` when closing. If the actual fix is in legacy-110's domain and this fragment is now incidentally fixed, mark it `resolved` and reference the upstream fix in the Resolution section.
8. **Commit + PR.** Use the **project-local** `/commit` skill (Safe Commit + PR Skill). Per `feedback_commit_skill_name_collision`, the global skill may load instead — if you see "Safe Commit Skill" without a PR step, follow up manually with `gh pr create` + `gh pr merge --auto --squash`.
9. **Verify auto-merge.** After `/commit` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push (per `feedback_commit_skill_renames_pr_branch`).

## Out of scope (do NOT expand into)
- Resolving legacy-110 in full (note progress in this PR's description if the fix happens to subsume it, but don't expand scope to chase the registry-drift root cause beyond what's needed to unblock the test).
- Other failing integration tests not connected to V2 schema setup.
- Refactoring `tests/integration/conftest.py` beyond the minimum to make the migration step deterministic.
- Touching unrelated `sql/` migrations.
- Concurrent worktree footprints: `src/llm/vision_client.py`, `scripts/benchmark_vision.py`, `tests/integration/extraction_v2/` — left to legacy-091 and legacy-116 picks.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_commit_skill_name_collision` — global vs project-local /commit
- `feedback_commit_skill_renames_pr_branch` — fetch headRefName before follow-up pushes
- `feedback_known_issues_pr_refs_int_not_string` — `- 261`, not `- '#261'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `feedback_run_recovery_before_verification` — run recovery before assuming a workaround removal failed
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR

## Return
The PR URL when done.

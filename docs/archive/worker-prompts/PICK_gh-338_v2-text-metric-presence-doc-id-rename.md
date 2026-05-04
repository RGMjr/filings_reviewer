You are working gh-338: rename `v2_text_metric_presence.doc_id` → `filing_id`.

## Source of truth
- Fragment: `docs/known-issues/gh-338-v2-text-metric-presence-doc-id-rename.md` (read in full before planning)
- Precedent: commit `a9b9984` (`refactor: rename doc_id → filing_id on remaining v2 tables`, gh-324) — same recipe applied to `v2_segments`, `v2_tables`, `v2_image_assets`, `v2_metric_definitions`. Read the diff (`git show a9b9984`) before planning; mirror its structure (idempotent migration guarded on `information_schema`, callsite sweep, test update).
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (`~/.claude/CLAUDE.md`) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm `v2_text_metric_presence.doc_id` still exists with the smell described (BIGINT FK to `filings(filing_id)` named `doc_id`). Check no other PR has renamed it since the fragment was written (2026-04-29). If already fixed, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode.
3. **Worktree-first.** First implementation step: `EnterWorktree fix/gh-338-presence-filing-id-rename`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.
4. **Pre-Implementation Gate** (per global CLAUDE.md). Show the completed checklist and get user approval before writing code. The ASSUMPTION AUDIT must verify (with grep/Read):
   - all `doc_id` references in `src/extraction_v2/persistence.py` (especially `_persist_text_metric_presence_in_tx`)
   - all `doc_id` references in `tests/integration/extraction_v2/test_presence_persistence.py`
   - any analytics views (`v_analytics_*`) that reference `v2_text_metric_presence.doc_id`
   - any scripts under `scripts/` that query the column directly
   - apply memory `feedback_sql_column_rename_four_passes` (same-line, alias refs, dict reads, log/Counter keys) and `feedback_partial_scope_rename_scoping` (qualify patterns with table name/alias to avoid corrupting other tables)
5. **Migration.** Generate via `python3 scripts/new_migration.py` (timestamp-prefixed filename per `.claude/rules/sql.md`). Make it idempotent: gate the `ALTER TABLE … RENAME COLUMN` on `information_schema.columns` showing the old name still present. Do NOT modify already-applied migrations (memory `feedback_migration_modification_checksum`).
6. **Tests.** Per project CLAUDE.md — `pytest -x -q --tb=short`. Update the integration test in lockstep. Don't skip on failures.
7. **Update fragment status as part of the same PR.** In `docs/known-issues/gh-338-v2-text-metric-presence-doc-id-rename.md`:
   - flip `status: open` → `resolved`
   - flip `autonomy: skip` → `n/a`
   - leave `pr_refs:` empty in the commit; the PR number is added after `gh pr create` returns it (per `feedback_known_issues_pr_refs_int_not_string`, write as `- <int>` not a string)
   - append a `### Resolution` section pointing to the new migration filename and the renamed callsites
   - do NOT add frontmatter fields outside `{pr_refs, gh_issue, note}` (per `feedback_known_issues_validator_optional_fields`)
8. **Commit + PR.** Use the **project-local** `/commit-proj` skill.
9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`.

## Out of scope (do NOT expand into)
- Any other `doc_id` smell on tables NOT in this fragment (gh-324 already covered the rest; if you find a new one, file a fresh `gh-N` fragment, do not bundle).
- Renaming `v2_documents.doc_id` itself — that is the actual document UUID PK, not an FK; do not touch it.
- Refactoring `_persist_text_metric_presence_in_tx` beyond the rename.
- Schema changes on adjacent tables.
- Any analytics-view rewrites beyond the column reference swap.

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_sql_column_rename_four_passes` — same-line, alias refs, dict reads, log/Counter keys
- `feedback_partial_scope_rename_scoping` — qualify column patterns with table name/alias
- `feedback_migration_modification_checksum` — never modify an already-applied migration; create a new one
- `feedback_known_issues_pr_refs_int_not_string` — `- 123`, not `- '#123'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR

## Return
The PR URL when done.

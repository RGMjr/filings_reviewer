You are working gh-314: Drop `filings.html_content` column after R2 soak window.

## User decision (load-bearing)

The user has confirmed via `/pick-issues` on 2026-05-05 that the R2 soak is complete and this column drop should proceed even though only 7 calendar days have elapsed since the fragment was discovered (2026-04-28). The fragment body says "≥30 days" — **do not bail on that criterion**. Proceed with the schema change.

## Source of truth

- Fragment: `docs/known-issues/gh-314-drop-filings-html-content-column.md` (read in full before planning)
- Project `CLAUDE.md` — read fully; obey "Implementation Rules", "Pre-Implementation Gate", "Workflow" (PR-required, worktree-first), and "Database" sections
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules", "Pre-Implementation Gate", and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Footprint warning

The fragment's `touches: ['sql/*', 'scripts/batch_v2_extraction.py']` is **undercounted**. As of origin/main on 2026-05-05, `git grep -l html_content -- src/ scripts/ tests/ sql/ config/` returns ~24 files. Build your plan from the real footprint, not the fragment's list.

Known real readers/writers (verify with grep before relying on this list):

- `src/filing_fetcher/filing_fetcher.py`
- `src/infra/document_source.py`, `src/infra/fmp_source.py`, `src/infra/huggingface_source.py`
- `scripts/batch_v2_extraction.py` (DB-blob fallback at lines 226–244 per fragment)
- `scripts/migrate_filing_html_to_r2.py`, `scripts/backfill_html_content.py`, `scripts/audit_filing_url_mismatch.py`, plus the presentation/transcript ingest scripts
- Tests: `tests/unit/filing_fetcher/test_filing_fetcher.py`, `tests/unit/infra/test_document_source.py`, `tests/unit/infra/test_fmp_source.py`, `tests/unit/test_batch_v2_extraction.py`, `tests/unit/extraction_v2/test_ingestion.py`, `tests/integration/test_migrate_filing_html_to_r2.py`, `tests/integration/test_migrate_onedrive_html_paths.py`

The original schema migration is `sql/10_add_html_content_column.sql`. **Do NOT modify it** (would break `schema_migrations` checksum — see memory `feedback_migration_modification_checksum`). Add a new timestamp-named migration via `scripts/new_migration.py`.

## Workflow

1. **Verify the issue is still relevant.** Re-read the fragment from origin/main. Run `git grep -l html_content -- src/ scripts/ tests/ sql/ config/` to confirm the column references are still present. Confirm `sql/10_add_html_content_column.sql` exists and the column is live in `filings`. Skip the "is the soak done" gate — user has overridden it (see top of prompt).

2. **Plan mode.** Use plan mode for the implementation. Run `/plan-review` before exiting plan mode. Plan must enumerate per-file what change is required (remove reference vs. switch to R2-only vs. leave historical script untouched).

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-314-drop-html-content-column`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`). This change touches 3+ files and includes a schema migration — the gate is required. Show the completed checklist and get user approval before writing code.

5. **Implementation.**
   - New timestamp-named migration via `scripts/new_migration.py` containing `ALTER TABLE filings DROP COLUMN html_content;`. Filename pattern per `.claude/rules/sql.md`.
   - Remove DB-blob fallback branches from `scripts/batch_v2_extraction.py` (lines 226–244). Apply equivalent removal to any other reader the grep surfaces. Per-file decisions belong in the plan:
     - **Remove** the `html_content` reference if the file uses it as a read-fallback after R2 (extraction call sites).
     - **Switch to R2-only** if the file writes to it and an R2 path is already in place.
     - **Leave historical** if the file is a one-time migration script (`backfill_html_content.py`, `migrate_filing_html_to_r2.py`) that's not run again — flag for user input rather than auto-delete.
   - Update tests that mock or assert on the column. Don't fix tests by deleting assertions — update them to reflect the new contract.
   - Update `.claude/rules/infrastructure.md` "Filing HTML Storage" section to remove the html_content-fallback mention (per fragment Next Steps item 4).

6. **Tests.** `pytest -x -q --tb=short`. Watch the integration tests above. Per project CLAUDE.md, do not skip on failures — iterate until clean. Note: `feedback_zero_facts_can_be_pre_pipeline_failure` — check `filings.html_fetch_error` first if the V2 extraction tests start emitting empty fact sets.

7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: skip` → `autonomy: n/a` (or omit entirely), set `pr_refs: [<this PR #>]` after PR creation, and append a `### Resolution` section describing the migration filename and the call sites updated. Per `project_fragment_only_closure_pattern`. Do not add frontmatter fields outside the validator allowlist (see `feedback_known_issues_validator_optional_fields`).

8. **Commit + PR.** Use the project-local `/commit-proj` skill. The global `/commit-user` skill works in a pinch but does not handle the project's pre-commit framework, fragment-system OOS triage, or required-checks recital — prefer `/commit-proj`.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Per `feedback_verify_auto_merge_after_commit`.

## Out of scope (do NOT expand into)

- R2 storage adapter changes — already shipped in #316 / gh-300.
- Deletion of historical migration scripts (`backfill_html_content.py`, `migrate_filing_html_to_r2.py`). If they appear unused, surface to the user — do not auto-delete in this PR.
- Editing `sql/10_add_html_content_column.sql` itself (checksum protection — see memory).
- Concurrent worktree footprints. Run `git worktree list` before starting; do not edit files inside other agents' worktrees.

## Memory references that apply

- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_migration_modification_checksum` — don't edit applied migrations; new timestamp migration
- `feedback_sql_column_rename_four_passes` — same multi-pass grep discipline applies to a column drop (same-line, alias refs, dict reads, log/Counter keys)
- `feedback_partial_scope_rename_scoping` — column references must be table-qualified when grepping multi-table queries
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside `{pr_refs, gh_issue, note}` when closing
- `feedback_known_issues_pr_refs_int_not_string` — `pr_refs:` must be list of ints (`- <N>`), not `'#<N>'`

## Return

The PR URL when done.

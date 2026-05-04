You are working legacy-038: `v2_metric_facts.doc_id` Is Misleadingly Named.

## Source of truth
- Fragment: `docs/known-issues/legacy-038-v2-metric-facts-doc-id-is-misleadingly-named.md` (read in full before planning)
- Project CLAUDE.md (repo root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (`~/.claude/CLAUDE.md`) — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply

## Goal
Rename `v2_metric_facts.doc_id` (BIGINT, refs `filings(filing_id)`) → `filing_id` so the column name matches its type and intent. The original mismatch produced a silent prod-only `operator does not exist: uuid = bigint` bug (commit `c353e83`); see fragment cross-refs.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`, check the touched files for changes since `updated: 2026-04-19`, and confirm the column is still named `doc_id`. If it's already renamed, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.
2. **Worktree-first.** First step: `EnterWorktree fix/legacy-038-doc-id-rename`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. Re-run `git worktree list` and check no in-flight worktree (`fix/gh-263`, `fix/gh-273`, `fix/gh-298`, `fix/gh-299`, `fix/gh-300`, `fix/legacy-075`, `fix+legacy-097`, gh-293, gh-294) has unmerged edits to `src/infra/db.py` or `src/extraction_v2/persistence.py` — those are the highest-collision files.
3. **Plan mode + `/plan-review`** before exiting plan mode.
4. **Pre-Implementation Gate** (per global CLAUDE.md) — show the completed checklist and get user approval before writing code. This change touches 15+ files, so the gate is required.
5. **Implementation order:**
   a. Generate migration: `python3 scripts/new_migration.py "rename v2 metric facts doc_id to filing_id"`. Body must be idempotent — wrap the rename in an `information_schema` existence check, do **not** use `EXCEPTION WHEN undefined_column` (it swallows real errors):
      ```sql
      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_name = 'v2_metric_facts' AND column_name = 'doc_id'
        ) THEN
          ALTER TABLE v2_metric_facts RENAME COLUMN doc_id TO filing_id;
        END IF;
      END $$;
      ALTER INDEX IF EXISTS idx_v2_metric_facts_doc_id RENAME TO idx_v2_metric_facts_filing_id;
      ```
   b. Append migration filename to `MIGRATION_ORDER` in `scripts/apply_all_migrations.py` (the `migration-order-check` pre-commit hook enforces this).
   c. Sweep callsites in `src/` and `scripts/`. Verify with `grep -rn 'v2_metric_facts.*doc_id\|"doc_id"\|fact\["doc_id"\]\|\.doc_id' src/ scripts/`. Pay special attention to **hardcoded `INSERT INTO v2_metric_facts (...)` column lists** (e.g. `src/infra/db.py:1577`) — those break at runtime, not lint time.
   d. Confirm whether `MetricFact` in `src/extraction_v2/models.py` exposes `doc_id` as a dataclass attribute. If yes, rename it and sweep `fact.doc_id` callers (separate from the dict-key `fact["doc_id"]` callers).
   e. Update tests, especially `tests/integration/test_migration_safety.py` which likely asserts on schema column names. Rerun incrementally — `pytest tests/integration/extraction_v2/ -x -q` first, then full `pytest -x -q --tb=short`.
   f. Remove the inline caveat comment in `src/universe/onboarding.py::REVIEW_DECISIONS_SQL` — the trap it warns about is gone after the rename.
6. **Do NOT edit `sql/09_v2_schema.sql` or `sql/38_create_analytics_views.sql`** — both are in the frozen `00-47` legacy range. Editing them breaks the migration checksum (per memory `feedback_hash_rule_change_transition`). PostgreSQL stores view column references as attnums (not name strings), so a `RENAME COLUMN` propagates automatically — `pg_get_viewdef` displays the new name and existing views keep working without re-creation. The `f.doc_id` text remaining in those frozen SQL files is cosmetic drift, not a functional issue.
7. **Tests.** `pytest -x -q --tb=short`. Don't skip on failures. If a pre-existing failure surfaces, follow the project CLAUDE.md "Pre-existing failures" workflow (`git stash` to confirm) before debugging.
8. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]` after PR creation (write `- 38` style — int, not `- '#38'`), append a `### Resolution` section. This is `project_fragment_only_closure_pattern` applied inline so the auto-closer doesn't need to reconcile later. Only add frontmatter fields in `{pr_refs, gh_issue, note}` — anything else trips the validator (`feedback_known_issues_validator_optional_fields`).
9. **Commit + PR via `/commit-proj`** (project-local Safe Commit + PR Skill). It handles pre-commit framework, fragment-system OOS triage, and required-checks recital. Do not use `/commit-user`.
10. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash` (per `feedback_verify_auto_merge_after_commit`).

## Out of scope (do NOT expand into)
- Any other column hygiene on `v2_metric_facts` (no `source_locator` work — see legacy-024).
- Editing frozen `sql/00*–sql/47*` migration files.
- Analytics view redesign (`sql/38_create_analytics_views.sql`).
- Any `v2_documents.doc_id` (UUID) references — that column genuinely IS a doc id and should NOT be renamed.
- Other open worktrees: `fix/legacy-075-image-queue-e2e`, `fix+legacy-097-chart-only-backfill`, `fix/gh-263`, `fix/gh-273`, `fix/gh-298`, `gh-299`, `gh-300`, gh-293, gh-294. Do not touch their footprints.

## Verification

End-to-end sanity check before opening the PR:

```bash
python3 scripts/apply_all_migrations.py
psql "$DATABASE_URL" -c "\d v2_metric_facts" | grep -E "filing_id|doc_id"   # expect filing_id, no doc_id
pytest -x -q --tb=short
pytest tests/integration/test_migration_safety.py -v
grep -rn 'v2_metric_facts.*doc_id\|"doc_id".*filing_id\|fact\["doc_id"\]' src/ tests/ scripts/
psql "$DATABASE_URL" -c "SELECT * FROM v_analytics_metric_coverage LIMIT 1;"
```

## Memory references that apply
- `feedback_verify_issue_status` — verify on `origin/main` first; check column is still `doc_id`.
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set.
- `feedback_hash_rule_change_transition` — DO NOT edit frozen `sql/09` or `sql/38`; the new migration's column rename is the path. Postgres auto-resolves dependent views.
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree; commit per step.
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + `### Resolution` section in the same PR.
- `feedback_known_issues_validator_optional_fields` — when closing the fragment, only add fields in `{pr_refs, gh_issue, note}`.
- `feedback_known_issues_pr_refs_int_not_string` — write `- 38`, not `- '#38'`.
- `feedback_scan_adjacent_defensive_code` — if you find adjacent stale comments/asserts about `doc_id`-vs-`filing_id`, file follow-ups; do not expand this PR.

## Return
The PR URL when done.

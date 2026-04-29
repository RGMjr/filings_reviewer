You are working gh-299: Stale OneDrive paths in `filings.html_storage_path` block re-extraction.

This is a **tactical** data-hygiene fix. The fragment is `autonomy: skip` because it requires prod data writes; the user has directed it for a worker prompt with explicit prod-write checkpoints.

**Important relationship to gh-300:** gh-300 ("Migrate filing HTMLs to R2") is the architectural follow-up that **supersedes** gh-299 by changing `html_storage_path` semantics from "filesystem path" to "opaque R2 storage key." If gh-300 ships first, gh-299 becomes moot. If gh-299 ships first, gh-300 will need to migrate again from the rewritten worktree-relative paths to R2 keys. **The user's stated intent is to ship both** — gh-299 first as a quick-fix to unstick re-extraction, then gh-300 as the medium-term architecture. Treat the work in this PR as known-temporary.

## Source of truth
- Fragment: `docs/known-issues/gh-299-stale-onedrive-paths-in-html-storage.md` (read in full from `origin/main` before planning)
- Cross-fragment: `docs/known-issues/gh-300-migrate-filing-htmls-to-r2.md` (read for awareness; do NOT implement here)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Git Operations" (destructive-action confirmation rules apply to prod data UPDATEs)
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/infrastructure.md` — `DATABASE_URL` is **Neon prod** in this project's `.env`. Test with `TEST_DATABASE_URL` first.
- Related context: `src/extraction_v2/stages/ingestion.py` (the consumer of `filings.html_storage_path`), `data/gold_standard/<Company>/filing.html` (the canonical local copies), schema definition for `filings` table in `sql/`.

## The bug (canonical from fragment)
5 known filings (`filing_ids` 1539, 1544, 1546, 1548, 1551 — Datadog, Maplebear, Samsara, Slack, Torrid) carry `filings.html_storage_path` values under `/Users/.../OneDrive-CMASB/.../data/gold_standard/<Company>/filing.html` with `NULL html_content`. OneDrive cloud-only files no longer hydrate reliably; 3 of 5 timed out during a 2026-04-28 backfill. Canonical local copies all exist at `data/gold_standard/<Company>/filing.html` (2–5 MB each). **Likely broader corpus-wide** — any filing ingested before the OneDrive→local migration may share the pattern.

## The fix shape (canonical from fragment "Next Steps")
1. **Audit** `filings` for `html_storage_path LIKE '/Users/%/OneDrive-CMASB/%'`. Count + report scope.
2. **Migration script** to rewrite paths to worktree-relative form, verifying each rewritten path resolves to a real file. Fall back to `sec_html_url` re-fetch for missing files.
3. **Optionally** populate `html_content` from disk so re-extraction does not depend on filesystem state.

## Workflow

1. **Verify the bug is still present + measure full scope.**
   ```bash
   git fetch origin main --quiet
   set -a && source .env && set +a
   psql "$DATABASE_URL" -c "
     SELECT COUNT(*) AS total,
            COUNT(*) FILTER (WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%') AS onedrive_paths,
            COUNT(*) FILTER (WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%' AND html_content IS NOT NULL) AS onedrive_with_content,
            COUNT(*) FILTER (WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%' AND html_content IS NULL) AS onedrive_null_content
       FROM filings;"
   ```
   Read-only; OK against prod. Capture the actual scope. Fragment names 5; expect more. If 0 rows match, the bug is already fixed — abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include:
   - **Decision: rewrite paths only, populate `html_content`, or both?** Recommended shape:
     - **Rewrite paths to worktree-relative form** (e.g. strip `/Users/.../OneDrive-CMASB/` prefix, resulting in `data/gold_standard/<Company>/filing.html`). Required.
     - **Populate `html_content` from disk in the same migration.** Recommended — removes filesystem dependency entirely so re-extraction works from DB alone. Skip only if `html_content` blob size becomes a Neon-storage concern (current corpus: ~5 MB × N filings, low).
     - **Fall back to `sec_html_url` re-fetch only for missing files** — fragments names this; necessary for paths that don't resolve to a real file post-rewrite. Throttle the SEC fetcher (existing 100ms minimum is fine for ≤100 filings).
   - **Documentation step** (per global Planning Rules):
     - Append a `### Recovering filings with stale storage paths` subsection under the existing operations docs (likely `docs/operations/` — find the right home; `TICKER_ONBOARDING.md` is plausible). Show the audit command, dry-run + apply, verification SQL.
     - Add a one-line cross-reference to gh-300 noting this is a tactical fix superseded by R2 migration.
   - **Migration script shape** (recommended): `scripts/migrate_onedrive_html_paths.py` with `--dry-run` (default), `--apply`, `--limit N` (process N filings), `--allow-prod` (refuse `--apply` against `*.neon.tech` without it).

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-299-onedrive-html-paths`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. **Verify** you are NOT in any of the in-flight worktrees.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:**
     - Confirm `data/gold_standard/<Company>/filing.html` exists for the 5 named filings: `ls -la data/gold_standard/{Datadog,Maplebear,Samsara,Slack,Torrid}/filing.html` (or whatever directory naming convention is used — check `data/gold_standard/`).
     - Confirm the schema for `filings.html_content`: BYTEA / TEXT / something else? Read the migration that created the column.
     - Confirm there is no other consumer of `html_storage_path` that hard-codes the OneDrive prefix (grep `OneDrive-CMASB` across the repo — should be zero non-fragment hits).
     - Confirm the `filings.sec_html_url` column exists and is populated for these rows (the fallback path depends on it).
   - **SCOPE CHECK:**
     - In: new `scripts/migrate_onedrive_html_paths.py`, docs append, fragment closure.
     - Out: any change to `src/extraction_v2/stages/ingestion.py`, the `filings` schema, `image_storage.py`, or any other consumer of `html_storage_path`. Those are gh-300 territory.
     - Out: gh-300's `src/infra/filing_storage.py` abstraction. **Specifically out** — the worker MUST NOT introduce that file as part of this PR. gh-300 is its own PR.
   - **RULES COMPLIANCE:**
     - Per `.claude/rules/infrastructure.md`: `DATABASE_URL` is Neon prod. The migration's `--apply` mode must refuse to run against `*.neon.tech` without an explicit `--allow-prod` flag. Dry-run mode is OK against prod (read-only).
     - Per `feedback_run_recovery_before_verification`: docs must show `--dry-run` first, `--apply` second.
     - Per `project_render_env_invisible_to_git_audit`: keep the prod guard in code, not in env.
   - **RISK ASSESSMENT:**
     - Wrong rewrite could point to a non-existent file. Mitigation: per-row file existence check; SEC fallback for missing.
     - Mid-migration interruption could leave the table in mixed state. Mitigation: each filing's UPDATE is its own transaction; resumable via `--limit` + already-rewritten rows being filtered out by the `LIKE '/Users/%/OneDrive-CMASB/%'` selector.
     - Concurrent `--watch` worker could pick up filings during migration. Low risk (re-extraction cycle is slow), but make migration idempotent: re-running on a clean corpus is a no-op.
     - **gh-300 will rewrite this column again** — the worktree-relative paths shipped here become an intermediate state. Make sure the worktree-relative format is unambiguous and recognizable so gh-300's migration can target them cleanly. Recommended format: bare relative path (`data/gold_standard/Datadog/filing.html`), no leading `./` or `/`.
   - **MINIMAL PATH:** confirmed above.
   - **WORKTREE CHECK:** yes (step 3).

   Show the completed checklist and **get user approval** before writing code.

5. **Implementation.**
   a. Create `scripts/migrate_onedrive_html_paths.py`:
      - Argparse: `--dry-run` (default), `--apply`, `--limit N` (default: no limit), `--allow-prod` (required for `--apply` against `*.neon.tech`), `--database-url` (default `$DATABASE_URL`).
      - Connect via `src.infra.db.DatabaseAdapter`.
      - Query: `SELECT filing_id, html_storage_path, sec_html_url FROM filings WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%' [LIMIT N]`.
      - For each row:
        - Strip the OneDrive prefix to get the worktree-relative path.
        - Check if the file exists at that path.
        - If yes: rewrite `html_storage_path` to the relative form; read file, populate `html_content` (bytes or text — match column type).
        - If no: log a warning; if `sec_html_url` is set, fetch via `SECClient` (respect 100ms rate limit), validate size > 15 KB (per memory `feedback_zero_facts_can_be_pre_pipeline_failure`), populate `html_content`, set `html_storage_path` to a deterministic format (e.g. the relative path for consistency).
        - If both fail: log an error; do not UPDATE; report at end.
      - Print a summary at the end: `audited=N rewritten=M fetched_from_sec=K failed=L`.
   b. Append a `### Recovering filings with stale storage paths` section to the appropriate operations doc (recommend `docs/operations/TICKER_ONBOARDING.md` since it's the existing home for this kind of recovery procedure — or create a new `docs/operations/onedrive-html-recovery.md` if the runbook prefers separation). Show the dry-run + apply commands, the prod-guard message, and a one-line note that gh-300 will supersede this with R2 storage.

6. **Tests.** Add tests in `tests/scripts/` (or wherever existing migration-script tests live):
   - **Dry-run does not write.** Fixture filing with OneDrive path. `--dry-run`. Assert: row unchanged, audit summary correct.
   - **Apply rewrites + populates content.** Same fixture + a real local file. `--apply`. Assert: `html_storage_path` is the relative form, `html_content` populated, byte length > 0.
   - **Missing file falls back to SEC.** Fixture with OneDrive path, no local file, `sec_html_url` set. Mock SEC fetch. Assert: `html_content` populated from mocked fetch.
   - **Prod-host guard.** `DATABASE_URL` ending in `.neon.tech`. `--apply --allow-prod=False`. Assert: refusal.
   - **Idempotency.** Run twice. Assert: second run is a no-op (no rows match the selector).
   Run: `pytest tests/scripts -x -q --tb=short`. Pre-existing failures: `git stash && pytest <case> -x -q && git stash pop`.

7. **PROD MIGRATION — STOP FOR EXPLICIT USER APPROVAL.**

   This step writes to prod. Print:
   - The exact command you intend to run.
   - The audit count from step 1 (e.g. "5 rows" or "N rows").
   - Expected outcome (rewritten paths + populated `html_content`).
   - Note: irreversible without a backup; original OneDrive paths are gone after the UPDATE.

   Ask: `"This is a prod data migration. Confirm 'yes, run the migration' to proceed."`

   On explicit `yes`:
   ```bash
   set -a && source .env && set +a
   FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \
   python3 scripts/migrate_onedrive_html_paths.py --apply --allow-prod 2>&1 | tee /tmp/gh_299_migration.log
   ```
   Capture the log. Verify the summary.

8. **Verify the outcome.**
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT COUNT(*) AS remaining_onedrive
       FROM filings
      WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%';"
   ```
   Expected: 0. If non-zero, surface the failed rows and stop.

   Spot-check one filing:
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT filing_id, html_storage_path, octet_length(html_content) AS content_bytes
       FROM filings WHERE filing_id = 1544;"
   ```
   Expected: relative `html_storage_path`, `content_bytes` > 100000.

9. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section that:
   - Names the migration (script path, runbook section).
   - Reports the migration counts (N audited, M rewritten, K fetched from SEC, L failed if any).
   - Cross-references gh-300 explicitly: "This is a tactical fix; gh-300 will replace `html_storage_path` semantics with R2 storage keys."
   Per `feedback_known_issues_pr_refs_int_not_string`, write `- 306` (or whichever PR # lands), not `- '#306'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`. Update `note:` to summarize what shipped (drop "skip" qualifier — the migration is now done).

10. **Commit + PR.** Use the **project-local** `/commit-proj` skill. Run from your worktree. The PR contains:
    - `scripts/migrate_onedrive_html_paths.py` (new)
    - `docs/operations/<runbook>.md` (append section, or new file)
    - `docs/known-issues/gh-299-...md` (closure)
    - Tests under `tests/scripts/`

11. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- gh-300's R2 storage abstraction. Specifically: do NOT create `src/infra/filing_storage.py`. Do NOT modify `src/extraction_v2/stages/ingestion.py` to use a new abstraction. That is gh-300's PR.
- Modifying the `filings` table schema (adding/removing columns).
- Re-extracting filings as part of this PR. The migration just rehydrates paths/content; re-extraction is a separate operator step.
- Applying the same fix to non-filings tables (`v2_image_assets.file_path` is a different concern with its own column-stickiness rules, see `.claude/rules/v2-pipeline.md`).
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097, in flight)
  - `src/universe/onboarding_runner.py`, `docs/operations/TICKER_ONBOARDING.md` (legacy-062, in flight; **note this is the docs file you'd most naturally append to — coordinate with the user if legacy-062's PR has not yet merged, or use a separate docs file**)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293, in flight)
  - `.claude/rules/web.md` (gh-294 PR #297)
  - `src/gold_standard/baseline.py`, `src/gold_standard/v2_validator.py` (gh-273, in flight)
  - `src/extraction_v2/persistence.py` (gh-298, in parallel)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first; the audit query in step 1 is the verification mechanism
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate the prod migration to a subagent, do **not**. The user-approval gate must be honored synchronously.
- `feedback_destructive_recovery_workflow` — bundle migration script in fix PR; execute the prod step under explicit approval; frame around ground-truth file resolution rather than abstract risk
- `feedback_run_recovery_before_verification` — show dry-run before apply in docs; verify post-migration before fragment closure
- `feedback_known_issues_pr_refs_int_not_string` — `- 306`, not `- '#306'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_zero_facts_can_be_pre_pipeline_failure` — if SEC fallback fetch returns < 15 KB, treat as failure not success
- `project_render_env_invisible_to_git_audit` — keep the `--allow-prod` guard in code, not env
- `project_db_query_vs_execute` — use `db.execute` for INSERT/UPDATE/DELETE without RETURNING

## Return
The PR URL when done, plus:
- Migration log summary (audited / rewritten / fetched / failed)
- Verification query output (remaining OneDrive paths = 0)
- One-line note flagging that gh-300 should be the next pick

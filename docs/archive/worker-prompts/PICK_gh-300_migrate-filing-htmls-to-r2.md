You are working gh-300: Migrate filing HTMLs to R2 long-haul storage.

This is a **medium-large architectural change**, not a quick fix. The fragment is `autonomy: skip` because it requires a real plan-mode design pass; the user has directed it for a worker prompt. Estimate: M-to-L. Plan-mode work is most of the value here.

**Sequencing constraint: gh-299 must ship first.** gh-299 is the tactical OneDrive-path fix that gets the prod data into a known-clean state. gh-300's migration starts from gh-299's worktree-relative paths and uploads the on-disk HTML to R2, replacing `html_storage_path` semantics from "filesystem path" to "opaque R2 storage key" (mirroring `v2_image_assets.file_path`). **Do not start gh-300 implementation until gh-299's PR has merged.**

## Source of truth
- Fragment: `docs/known-issues/gh-300-migrate-filing-htmls-to-r2.md` (read in full from `origin/main` before planning)
- Cross-fragment: `docs/known-issues/gh-299-stale-onedrive-paths-in-html-storage.md` (precondition — verify it has merged before implementing)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**. Pay attention to design principles 4 (Conservative classification — analogue here is conservative migration) and 6 (Reviewed-filing guard — re-extraction implications must stay safe).
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules", "Planning Rules", and "Git Operations" (destructive-action rules apply to the prod migration step)
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/infrastructure.md` — **authoritative** for R2 patterns (`R2Storage`, `LocalFilesystemStorage`, `FILINGS_REVIEWER_ALLOW_PROD_WRITES`, `validate_key`). The new `FilingStorage` abstraction must mirror this surface.
- `.claude/rules/v2-pipeline.md` — `Image Asset Identity` section explains the storage-key + UPSERT pattern that `filing_storage` should mirror
- Related context (read for shape, modify only as required): `src/infra/image_storage.py` (the canonical reference implementation — your new `filing_storage.py` is the same shape for HTML), `src/extraction_v2/stages/ingestion.py` (the consumer of `filings.html_storage_path` — your refactor target), `tests/integration/test_full_page_ocr_pipeline.py` and other ingestion tests (the regression-protection surface)

## The work (canonical from fragment "Next Steps")
1. **New `src/infra/filing_storage.py` abstraction** analogous to `image_storage.py`. `R2FilingStorage` (prod) + `LocalFilesystemFilingStorage` (dev), gated by `FILINGS_REVIEWER_ALLOW_PROD_WRITES` env. Identical safety contract: writes refused without the env, reads always allowed. Backend selected at runtime via `R2_BUCKET` env.
2. **Refactor `src/extraction_v2/stages/ingestion.py`** to fetch HTML via the storage abstraction (opaque storage key in `html_storage_path`) instead of `Path(...).read_text()`. The column changes meaning: filesystem path → R2 storage key (e.g. `filings/<cik>/<accession>/primary.htm`). Other consumers of `html_storage_path` need the same refactor.
3. **One-time migration script** to upload each filing's HTML bytes to R2 under deterministic keys and rewrite `html_storage_path`. The migration reads from gh-299's worktree-relative paths and `html_content` blobs.
4. **Update other consumers of `html_storage_path`** — reviewer UI source-rendering, any analytics views, any scripts that resolve the column.

## Workflow

1. **Verify gh-299 has merged.**
   ```bash
   git fetch origin main --quiet
   gh pr list --state merged --search "gh-299" --json number,title,mergedAt | head
   psql "$DATABASE_URL" -c "
     SELECT COUNT(*) FILTER (WHERE html_storage_path LIKE '/Users/%/OneDrive-CMASB/%') AS onedrive_paths,
            COUNT(*) FILTER (WHERE html_storage_path LIKE 'data/gold_standard/%') AS worktree_relative,
            COUNT(*) FILTER (WHERE html_content IS NOT NULL) AS has_content
       FROM filings;"
   ```
   Expected: 0 OneDrive paths, all eligible filings have either worktree-relative paths or `html_content` populated. If OneDrive paths remain, gh-299 isn't done — STOP and surface to user. Do not begin gh-300 implementation; gh-300 assumes gh-299's clean state.

2. **Verify the issue is still relevant** by spot-checking the consumers.
   ```bash
   rg -nE "html_storage_path|html_content" src/extraction_v2/stages/ingestion.py src/web/ scripts/ | head -30
   ```
   Confirm `ingestion.py` still reads `html_storage_path` as a filesystem path. List every other file that reads the column — those are your refactor surface.

3. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. **The plan is most of the work for this PR.** It must include:

   - **Storage-key shape decision.** Recommended: `filings/<cik>/<accession>/primary.htm`. Mirrors `pipeline/<cik>/<accession>/<filename>` from image storage. Surface alternatives (e.g. `filings/<filing_id>/primary.htm`) and trade-offs (CIK+accession is human-debuggable; filing_id is opaque) — let user pick.
   - **Column semantics decision.** Two options:
     - **A. Reuse `html_storage_path`** with a different semantic (filesystem path → R2 storage key). Smallest schema diff. But the column name becomes a lie.
     - **B. Add `html_storage_key` column, deprecate `html_storage_path`, drop the latter in a follow-up migration.** Cleaner long-term. Larger schema diff and a deprecation tail.
     Recommended: **A** with a one-line comment in the schema/migration explaining the semantic shift, plus a follow-up fragment for an eventual rename. Surface to user; let them redirect to B if they prefer.
   - **Migration parity decision.** Should the migration drop `html_content` after R2 upload? Trade-off: smaller Neon DB; loses the fallback if R2 reads fail. Recommended: **keep `html_content` for now**, file a follow-up fragment to drop it once R2 has been the source of truth for ≥30 days without incident.
   - **Documentation step** (per global Planning Rules):
     - Update `.claude/rules/infrastructure.md` "Image Storage" → rename to "Image and Filing Storage" or add a new section explaining the parallel `filing_storage.py` abstraction.
     - Update `.claude/rules/v2-pipeline.md` if it documents `html_storage_path` semantics anywhere.
     - Update CLAUDE.md "Database" section to note that filing HTML lives in R2 (analogue to the image-bytes note).
     - Add a `### Migrating filing HTMLs to R2` runbook under `docs/operations/` with the migration command, dry-run, verification SQL.
   - **Test plan.**
     - Unit tests for `LocalFilesystemFilingStorage` and `R2FilingStorage` (both directions: get/put).
     - Integration test: ingestion reads HTML via the storage abstraction (LocalFilesystemFilingStorage in tests).
     - Migration script: dry-run + apply tests with a fixture filing.
     - Reviewer UI source-rendering: spot-check a UI route resolves the column correctly via Playwright (if practical) or assert the route handler reads via the abstraction.
   - **Stages.** Recommend splitting into 2 PRs:
     - **PR 1 (this prompt):** abstraction + migration script + ingestion refactor + UI refactor + docs. Migration runs against prod under approval gate.
     - **PR 2 (follow-up fragment):** drop `html_content` column after a soak window. **Do not include in PR 1.**

4. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-300-filing-htmls-to-r2`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. **Verify** you are NOT in any of the in-flight worktrees, and that gh-299's PR has merged into `main`.

5. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:**
     - Confirm `R2_BUCKET` is set on the prod env (`render.yaml`'s `filings-shared-secrets`); confirm `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` is set on the services that need to write filing HTML (extraction, ingestion-runner). If not, the migration won't be able to upload — flag to user as a precondition.
     - Confirm `boto3` is in `requirements.txt`. (It will be — image_storage uses it.)
     - Confirm the existing `image_storage.py`'s `validate_key` semantics are appropriate for filing keys (path-traversal rejection, absolute-path rejection). Reuse or replicate.
     - Confirm the `filings` schema's current column types: `html_storage_path` (TEXT?), `html_content` (BYTEA / TEXT?). The R2 round-trip should match `html_content`'s encoding.
     - Confirm there is no critical UI feature that needs synchronous local-filesystem access to filing HTML. R2 reads add ~50–200ms latency.
   - **SCOPE CHECK:**
     - In: `src/infra/filing_storage.py` (new), `src/extraction_v2/stages/ingestion.py` refactor, migration script, UI consumer refactor, docs, tests, fragment closure.
     - Out: dropping `html_content` column. Schema column rename (`html_storage_path` → `html_storage_key`). Adding new fields to `filings`. Migrating other table columns. Render service config changes (env vars are out of scope; verify they exist as a precondition).
     - Out: gh-298 (chart-only drain — separate PR) and gh-299 (already merged precondition).
   - **RULES COMPLIANCE:**
     - The new `R2FilingStorage.put_bytes` MUST refuse without `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` (mirror `R2Storage` exactly). Reads remain open.
     - Per `project_render_env_invisible_to_git_audit`: keep the prod-write guard in code, not in env config.
     - Per `feedback_run_recovery_before_verification`: docs must show migration dry-run before apply.
     - Per design principle 6 (reviewed-filing guard): the ingestion refactor must NOT change the contract under which `_persist_facts_in_tx` raises `ReviewedFilingError`. The HTML source change is upstream of fact persistence; verify with an integration test.
   - **RISK ASSESSMENT:**
     - **Migration is the highest-risk step.** Each filing's HTML uploaded to R2; `html_storage_path` rewritten in a separate transaction. If the upload succeeds and the UPDATE fails, R2 has an orphan key (cheap, recoverable). If the UPDATE succeeds and the upload failed, the column points to a missing key — re-extraction will fail on read.
       - Mitigation: verify R2 write succeeded (HEAD on the key) BEFORE the UPDATE; on UPDATE failure, do not delete the R2 key (orphans are cheap, lost data is not).
     - **Read latency change.** Ingestion now hits R2 instead of local disk. Cache helpfully, but don't over-engineer.
     - **gh-299's `html_content` blobs are the migration source.** If gh-299 didn't fully populate `html_content` (e.g. the SEC fallback failed for some rows), those rows can't be migrated to R2 from the DB alone — they'd need a fresh SEC fetch. Plan for this: the migration script should detect `html_content IS NULL`, log, and either re-fetch from `sec_html_url` (with the existing SEC throttle) or skip+report.
     - Concurrent worktree footprints (do NOT touch):
       - `worktree-fix+legacy-097-chart-only-backfill`: scripts/audit_residual_chart_facts.py, fragment.
       - `claude/feat-gh-293-...`: web routes + UI templates + JS.
       - `claude/feat-gh-294-...` (PR #297): UI templates + JS + web rules.
       - `fix-gh-273-gs-gate-rerun-on-fail`: gold_standard/.
       - `fix-gh-263-fragment-closure` (PR #304): fragment only.
       - `feat-render-deploy-speed-pr2`: large grab-bag including Dockerfile and render.yaml — coordinate if you need to touch any deploy config.
     - **gh-298 may be in parallel** — both touch `src/extraction_v2/persistence.py` only IF gh-300's ingestion refactor incidentally touches persistence. It shouldn't (HTML source is upstream of persistence). Verify your refactor does not change persistence.py.
   - **MINIMAL PATH:** confirmed above; the PR is bigger than usual, but each piece is required for the abstraction to land cleanly.
   - **WORKTREE CHECK:** yes (step 4).

   Show the completed checklist and **get user approval** before writing code.

6. **Implementation.**
   a. **`src/infra/filing_storage.py`** — new file. Mirror `src/infra/image_storage.py` exactly:
      - Abstract `FilingStorage` protocol: `get_bytes(key) -> bytes`, `put_bytes(key, data) -> None`, `exists(key) -> bool`, `validate_key(key)`.
      - `LocalFilesystemFilingStorage` rooted at `<repo>/data/filing_cache/` (or new env `FILING_CACHE_DIR`).
      - `R2FilingStorage` wrapping the same boto3 S3-compatible client. Bucket: `R2_BUCKET` (shared with images is fine; key prefix `filings/` separates).
      - Factory: `make_filing_storage()` returns R2 if `R2_BUCKET` is set, Local otherwise.
      - Prod-write guard on `R2FilingStorage.put_bytes`: refuse without `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1`.
   b. **Refactor `src/extraction_v2/stages/ingestion.py`** to read via the abstraction. Remove direct `Path(...).read_text()` calls on `html_storage_path`. The column now stores opaque storage keys.
   c. **Refactor other consumers** (from step 2 grep). UI source-rendering routes: read via the abstraction. Analytics views: confirm none JOIN on the column directly (filesystem paths in views were always wrong).
   d. **`scripts/migrate_filing_html_to_r2.py`** — new file. Argparse: `--dry-run` (default), `--apply`, `--limit N`, `--allow-prod` (required for `--apply` against `*.neon.tech`).
      - For each `filings` row with `html_storage_path` not yet in R2 storage-key shape:
        - Source: prefer `html_content` (from gh-299); fall back to `Path(html_storage_path).read_bytes()` if local; fall back to SEC fetch if `sec_html_url` set.
        - Compute storage key: `filings/<cik>/<accession>/primary.htm` (or whatever shape the plan-mode decision picked).
        - `R2FilingStorage.put_bytes(key, html_bytes)`.
        - Verify with `R2FilingStorage.exists(key)` HEAD.
        - On verified upload: UPDATE `filings SET html_storage_path = %(key)s WHERE filing_id = %(id)s`.
        - On any failure: log and continue; do NOT update the column for that row.
      - Print summary: `audited=N migrated=M sec_fetched=K skipped=L failed=F`.
   e. Update docs (per plan).

7. **Tests.**
   - Unit tests for both `FilingStorage` backends (round-trip, key validation, prod-write guard, missing key returns False on `exists`).
   - Integration test: refactored `ingestion.py` reads HTML via `LocalFilesystemFilingStorage`. Existing `tests/integration/extraction_v2/` tests should pass — verify they still do (don't break the gh-262 fixture pattern that redirects to LocalFilesystemStorage in tests).
   - Migration script: dry-run vs apply, prod-host guard, `html_content` source path, SEC fallback path, idempotency.
   - Run: `pytest tests/integration tests/unit -x -q --tb=short`. Pre-existing failures: `git stash && pytest <case> -x -q && git stash pop`.

8. **PROD MIGRATION — STOP FOR EXPLICIT USER APPROVAL.**

   This step uploads N filings' HTML to prod R2 and rewrites `filings.html_storage_path` semantics for those rows. It is forward-recoverable (R2 keys can be re-uploaded if state diverges) but the column rewrite is hard to undo without per-row reconciliation.

   Print:
   - Audit count (N rows about to migrate).
   - Estimated R2 storage growth (N × avg_html_size; should be small — fragment estimates ~$1/month for full corpus).
   - Expected outcome (column values change shape; ingestion now reads via R2).

   Ask: `"This is a prod migration that changes filings.html_storage_path semantics. Confirm 'yes, run the migration' to proceed."`

   On explicit `yes`:
   ```bash
   set -a && source .env && set +a
   FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 \
   python3 scripts/migrate_filing_html_to_r2.py --apply --allow-prod 2>&1 | tee /tmp/gh_300_migration.log
   ```

9. **Verify.**
   ```bash
   psql "$DATABASE_URL" -c "
     SELECT COUNT(*) FILTER (WHERE html_storage_path LIKE 'filings/%/%/%') AS r2_keys,
            COUNT(*) FILTER (WHERE html_storage_path NOT LIKE 'filings/%/%/%') AS not_yet_migrated,
            COUNT(*) AS total
       FROM filings;"
   ```
   Expected: `r2_keys` ≈ migration target count; `not_yet_migrated` matches expected leftovers (e.g. rows with no source).
   - Spot-check one filing through the refactored ingestion path: re-extract a non-reviewed test filing end-to-end, confirm `process_filing` succeeds reading from R2.

10. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section that:
    - Names the abstraction (`src/infra/filing_storage.py`), the refactored consumers, the migration script, and the updated docs.
    - Reports migration counts.
    - Notes the deferred follow-up: drop `html_content` column after a soak window. File as a separate fragment if not already filed.
    - Cross-references gh-299: "gh-299's worktree-relative paths and `html_content` populated fields were the migration source."
    Per `feedback_known_issues_pr_refs_int_not_string`, write `- 312` (or whichever PR # lands), not `- '#312'`. Per `feedback_known_issues_validator_optional_fields`, don't add frontmatter fields outside `{pr_refs, gh_issue, note}`. Update `note:` to summarize what shipped.

11. **Commit + PR.** Use the **project-local** `/commit-proj` skill. Run from your worktree. The PR is medium-large (4–8 source files, 2 docs, tests, plus the migration script) — expect CI to take longer than usual; don't panic if Integration Tests run > 10 min.

12. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Dropping the `html_content` column. **File a follow-up fragment** for it post-soak; do not do it in this PR.
- Renaming `html_storage_path` to `html_storage_key`. Surface in plan-mode; default to keeping the name.
- Migrating other tables' filesystem paths to R2 (e.g. gold-standard fixtures, transcript files). Different columns, different decisions.
- Modifying `image_storage.py` or any image-side logic.
- Render service config changes (R2 env vars, bucket creation). Verify these as preconditions; flag missing ones to user.
- gh-299 work. Precondition; if gh-299 hasn't merged, STOP.
- gh-298 work. Independent track in `src/extraction_v2/persistence.py`.
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097, in flight)
  - `src/universe/onboarding_runner.py`, `docs/operations/TICKER_ONBOARDING.md` (legacy-062, in flight; if you need to add docs, use a separate file under `docs/operations/`)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293, in flight) — but the UI source-rendering refactor MAY need to touch one of these. **Coordinate with the user** before editing any of these files; gh-293 must merge first OR your PR splits the file with a careful merge plan.
  - `.claude/rules/web.md` (gh-294 PR #297)
  - `src/gold_standard/baseline.py`, `src/gold_standard/v2_validator.py` (gh-273, in flight)
  - Dockerfile, render.yaml (`feat-render-deploy-speed-pr2` worktree)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first; verify gh-299 has merged
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate the prod migration to a subagent, do **not**. The user-approval gate must be honored synchronously.
- `feedback_destructive_recovery_workflow` — bundle migration script in fix PR; execute under explicit approval; frame around column-semantic change rather than abstract risk
- `feedback_run_recovery_before_verification` — show dry-run before apply
- `feedback_known_issues_pr_refs_int_not_string` — `- 312`, not `- '#312'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_zero_facts_can_be_pre_pipeline_failure` — SEC fallback fetch results < 15 KB are failures
- `project_render_env_invisible_to_git_audit` — keep the prod-write guard in code, not env
- `project_db_query_vs_execute` — use `db.execute` for INSERT/UPDATE/DELETE without RETURNING

## Return
The PR URL when done, plus:
- Migration log summary (audited / migrated / sec_fetched / skipped / failed)
- Verification query output (R2 keys count vs not_yet_migrated)
- One-line note on the deferred `html_content` drop follow-up (which fragment file, if filed)

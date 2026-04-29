You are working legacy-062: Local-Dev Stuck-Batch Recovery Is Manual — ship the remaining `--cleanup-stuck` admin flag (NS2) plus the SIGTERM log-line update (NS3 trailer).

## Source of truth
- Fragment: `docs/known-issues/legacy-062-local-dev-stuck-batch-recovery-is-manual.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/infrastructure.md` — for `DATABASE_URL` / `TEST_DATABASE_URL` separation. The cleanup tool must not silently fall back to prod.
- Related context (read for shape, modify only as required): `src/universe/onboarding_runner.py` (the CLI you're extending — see lines ~395–476 for the existing argparse surface, lines ~54–60 for the SIGTERM handler), `docs/operations/TICKER_ONBOARDING.md` (the recovery doc shipped under NS1 — your `--cleanup-stuck` section appends here), and any `tests/integration/universe/` tests that already cover the runner.

## Status note (read first)
Fragment is **`partially-resolved`**. NS1 (docs) and NS3 (SIGTERM signal-trap) already shipped. **Remaining work, per fragment "Remaining":**

> NS2 (`--cleanup-stuck` admin flag) — `python3 -m src.universe.onboarding_runner --cleanup-stuck` admin mode that scans for batches with `run_lock_until < NOW() - INTERVAL '1 hour'` still in `running` state and either marks them failed or re-claims them. Once shipped, update the SIGTERM log message to point operators at the flag.

The fragment leaves one design call unmade: **mark-failed vs re-claim.** Resolve it in plan mode (see Pre-Implementation Gate below).

## Workflow

1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Confirm `--cleanup-stuck` is still absent:
   ```bash
   git fetch origin main --quiet
   grep -nE "cleanup-stuck|cleanup_stuck" src/universe/onboarding_runner.py
   ```
   At brief time the grep was empty. If a flag has appeared since `updated: 2026-04-28`, abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

   Also confirm NS1 and NS3 are still in place (don't re-ship them):
   - `grep -nE "Shutdown signal received|Recovering a stuck batch" src/universe/onboarding_runner.py docs/operations/TICKER_ONBOARDING.md`

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include:

   **Decision: mark-failed vs re-claim.** Recommended shape:
   - **Default behavior: mark-failed.** Set `status='failed'`, `finished_at=NOW()`, `run_lock_until=NULL` on the matched rows. Why: re-claiming is what `--watch` mode already does (its `claim_next_queued_batch` picks up rows with expired `run_lock_until` automatically). The point of `--cleanup-stuck` is the *opposite* — give the operator a clean way to abandon dead batches that `--watch` won't retry (e.g., the underlying filing is broken, or the operator wants the batch out of the way). Failed rows are visible in the UI; the operator can re-queue manually if needed.
   - **No re-claim mode.** Don't add an `--reclaim` toggle as part of this PR. If a future use case wants it, ship as a separate fragment.
   - Surface this recommendation to the user during plan-review and let them redirect to "support both modes" if they prefer. Do NOT ship both modes silently.

   **Documentation step** (per global Planning Rules):
   - Append a `### Cleaning up stuck batches with --cleanup-stuck` subsection under the existing "Recovering a stuck batch (local dev)" heading in `docs/operations/TICKER_ONBOARDING.md`. Show the dry-run + apply invocations, and the threshold flag.
   - Update the SIGTERM log message in `_signal_handler` to mention the flag (NS3 trailer).
   - No changes to `.claude/rules/*` are needed for this work.

   **CLI shape** (recommended, surface in plan-review):
   - Extend the mutually-exclusive `mode_group` in `main()` with a third option: `--cleanup-stuck`.
   - Add `--apply` flag (default: dry-run that lists affected `batch_id`s without writing). Operators always see the candidate list before any UPDATE.
   - Add `--stuck-threshold` (default: `'1 hour'`) for tunability — pass through as a Postgres interval string.
   - Print a one-line summary on completion: `cleanup-stuck: matched=N marked_failed=M (dry-run | applied)`.

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/legacy-062-cleanup-stuck-flag`. The PreToolUse hook denies HEAD-moving git ops in the primary tree. **Verify** you are NOT in the `fix+legacy-097-chart-only-backfill` worktree — that's the parallel chart-drain track and must not pick up your changes.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:**
     - Confirm `v2_ingest_batches` schema has `status`, `run_lock_until`, `finished_at` columns (read the migration in `sql/` that creates the table).
     - Confirm `v2_ingest_batch_filings` is FK'd to `v2_ingest_batches.batch_id` and the cleanup behavior on the batch-level UPDATE is what you want — does flipping a batch's `status='failed'` cascade or otherwise affect the per-filing rows? If yes, reflect that in the docs section. The fragment's NS1 docs may already capture the manual recovery shape — mirror it.
     - Confirm `argparse`'s mutually-exclusive group accepts a third option without breaking `--batch-id` / `--watch`.
   - **SCOPE CHECK:**
     - In: NS2 implementation + NS3 trailer (one-line SIGTERM log update) + docs append + tests.
     - Out: any change to `--watch` mode's claim semantics, any new lock-acquisition logic, any UI surface, any change to how batches are queued.
   - **RULES COMPLIANCE:**
     - **`DATABASE_URL` vs `TEST_DATABASE_URL`** (`.claude/rules/infrastructure.md`): the runner already calls `load_dotenv()` and reads `DATABASE_URL`. **In this project's `.env`, `DATABASE_URL` is Neon prod.** A `--cleanup-stuck --apply` run pointing at prod would mark prod batches failed. That's destructive and irreversible. Add a guard: refuse `--apply` mode when `DATABASE_URL` matches a production hostname (`*.neon.tech`) **unless** an explicit `--allow-prod` flag is set. Dry-run mode is fine against prod (no writes). Explain this in the docs section.
     - Per `feedback_run_recovery_before_verification`, **the docs must show dry-run first, then apply** so operators don't accidentally write before inspecting.
   - **RISK ASSESSMENT:**
     - Wrong threshold could mark a still-active batch failed. The 1-hour default + the dry-run-first contract + the prod guard mitigate this.
     - Concurrent `--watch` running in another process could race the cleanup UPDATE. The existing `run_lock_until` semantics are the right primitive — only target rows where `run_lock_until < NOW() - <threshold>` AND `status='running'`. A live watcher would have a current-or-future `run_lock_until`, so it's filtered out by construction.
     - Concurrent worktree footprints (do NOT touch):
       - `worktree-fix+legacy-097-chart-only-backfill`: `scripts/audit_residual_chart_facts.py` + the legacy-097 fragment.
       - Active gh-293 work (image-card undo affordance): `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js`.
       - Active gh-294 work (image-tab keyboard shortcuts): `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js`, `.claude/rules/web.md`.
     - None of those overlap your `touches:` (`docs/operations/*`, `src/universe/onboarding_runner.py`).
   - **MINIMAL PATH:** confirmed above.
   - **WORKTREE CHECK:** yes (step 3).

   Show the completed checklist and **get user approval** before writing code. Per global `CLAUDE.md`: "Show the completed checklist and get user approval before proceeding with implementation."

5. **Implementation.**
   a. Add the `--cleanup-stuck` mode to `main()` in `src/universe/onboarding_runner.py`. Extend `mode_group`, add `--apply`, `--stuck-threshold`, and `--allow-prod` flags. Implement the prod-host guard (refuse `--apply` against `*.neon.tech` without `--allow-prod`).
   b. Implement a `cleanup_stuck_batches(db, threshold: str, apply: bool) -> dict` helper alongside the existing `claim_*` helpers. The helper:
      - SELECTs candidates: `WHERE status='running' AND run_lock_until < NOW() - INTERVAL %s` (parameterized — Postgres `make_interval` or formatted at the SQL boundary; **never f-string user input into SQL**).
      - When `apply=True`: UPDATE matched rows to `status='failed'`, `finished_at=NOW()`, `run_lock_until=NULL`.
      - Returns `{matched: N, marked_failed: M}` (M == 0 in dry-run).
   c. Print the candidate `batch_id` list before the UPDATE (so the operator sees what's about to change even in `--apply` mode). Use `logger.info`, not stdout.
   d. Update `_signal_handler` log line: change "Shutdown signal received (%s); will stop after current filing." to mention the flag, e.g. `"Shutdown signal received (%s); will stop after current filing. To recover stuck batches afterwards, run: python3 -m src.universe.onboarding_runner --cleanup-stuck"`. Keep it one line.
   e. Update `docs/operations/TICKER_ONBOARDING.md`: append `### Cleaning up stuck batches with --cleanup-stuck` under the existing "Recovering a stuck batch (local dev)" heading. Show:
      - The dry-run command + sample output.
      - The `--apply` command + the prod-guard message + how to override with `--allow-prod`.
      - The threshold tunability with `--stuck-threshold`.
      - A note that `--cleanup-stuck` is "abandon, don't retry" — `--watch` already re-claims expired rows automatically.

6. **Tests.** Add tests in `tests/integration/universe/` (or wherever the runner's existing tests live — find with `rg -l "onboarding_runner" tests/`):
   - **Dry-run identifies stuck rows but does not write.** Set up a fixture batch with `status='running'` and `run_lock_until = NOW() - INTERVAL '2 hours'`. Run `cleanup_stuck_batches(db, '1 hour', apply=False)`. Assert: `matched == 1`, `marked_failed == 0`, DB row still `status='running'`.
   - **Apply mode writes.** Same fixture; `apply=True`. Assert: `matched == 1`, `marked_failed == 1`, DB row now `status='failed'`, `finished_at IS NOT NULL`, `run_lock_until IS NULL`.
   - **Threshold honored.** Fixture row at `NOW() - INTERVAL '30 minutes'`, threshold `'1 hour'`. Assert: `matched == 0` (too fresh).
   - **Live watcher not flagged.** Fixture row with `run_lock_until = NOW() + INTERVAL '5 minutes'` and `status='running'`. Assert: `matched == 0`.
   - **Prod-host guard.** Mock `DATABASE_URL` ending in `.neon.tech`; call with `apply=True, allow_prod=False`. Assert: function refuses (raises a clear error or returns a typed refusal — your choice; surface in plan-review).
   Run: `pytest tests/integration/universe -x -q --tb=short`. Per project `CLAUDE.md` testing standards. Pre-existing failures: `git stash && pytest <case> -x -q && git stash pop`.

7. **Update fragment status as part of the same PR.** Flip `status: partially-resolved` → `resolved`, set `pr_refs: [<this PR #>]`, append a `### Resolution` section that:
   - Names what shipped: `--cleanup-stuck` mode (dry-run default + `--apply` + `--stuck-threshold` + prod-host guard with `--allow-prod` override), SIGTERM log update, docs append.
   - Notes the design call resolution: chose mark-failed as the default (rationale: `--watch` already re-claims expired rows; `--cleanup-stuck` is the abandon path).
   - Test coverage summary: `<N>` integration tests under `tests/integration/universe/`.
   Per `feedback_known_issues_pr_refs_int_not_string`, write `- 296` (or whichever PR number lands), not `- '#296'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`. Update `note:` to drop the "needs design call" qualifier; replace with a one-line summary of what shipped.

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit-user`. Run from your worktree.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Changing `--watch` mode's claim semantics or adding new lock-acquisition primitives.
- A `--reclaim` mode for `--cleanup-stuck` (separate fragment if anyone wants it).
- Any UI affordance for stuck-batch cleanup. The fragment scope is CLI + docs only.
- Cleanup of `v2_ingest_batch_filings` partial rows beyond what flipping the parent batch's status implies. If the existing FK/CASCADE behavior is insufficient, file a follow-up fragment — don't expand here.
- Changes to `v2_ingest_batches` schema, indexes, or constraints.
- Any bigger refactor of `onboarding_runner.py` ("the CLI is messy" is not in scope).
- Concurrent in-flight work — do **not** touch:
  - `scripts/audit_residual_chart_facts.py`, `docs/known-issues/legacy-097-...md` (legacy-097 in flight, parallel)
  - `src/web/routes/api_unified.py`, `src/web/routes/review_unified.py`, `src/web/templates/unified_review.html`, `src/web/static/js/review_images_v2.js` (gh-293 in flight, parallel)
  - `.claude/rules/web.md` (gh-294 in flight, parallel)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set after `/commit-proj`
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — write `- 296`, not `- '#296'`
- `feedback_known_issues_validator_optional_fields` — `OPTIONAL_FIELDS` allowlist is `{pr_refs, gh_issue, note}`
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_run_recovery_before_verification` — show dry-run before apply in the docs; do not let operators write blind
- `feedback_close_partially_resolved_cleanly` — closing partially-resolved fragments cleanly is the goal; don't leave NS2 deferred again
- `project_render_env_invisible_to_git_audit` — Render env-group config is invisible to git; default new safety controls (the `--allow-prod` guard) to code, not env vars

## Return
The PR URL when done.

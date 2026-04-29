You are working gh-262: R2 prod-write guard fails 10 e2e tests on a clean main during local pytest.

## Source of truth
- Fragment: `docs/known-issues/gh-262-r2-prod-write-guard-blocks-local-pytest.md` (read in full from `origin/main` before planning)
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules"
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply
- `.claude/rules/infrastructure.md` — **authoritative** for image-storage and R2 prod-write guard semantics. Read before changing the guard or the storage backend.
- Related context (read for shape): `src/infra/image_storage.py` (the guard lives here), `tests/integration/extraction_v2/test_e2e_pipeline.py`, `tests/integration/test_full_page_ocr_pipeline.py`, and the existing pytest fixtures under `tests/conftest.py` / `tests/integration/conftest.py`.

## The problem (summary — fragment is canonical)
Sourcing `.env` (which sets `R2_BUCKET` to the prod bucket and matching R2 creds) without also setting `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` causes 10 integration tests on a clean `origin/main` to fail with `Refusing R2 write — set FILINGS_REVIEWER_ALLOW_PROD_WRITES=1 to allow.` The guard is intentional and correct (`.claude/rules/infrastructure.md`); the failure is a local-DX problem. Fixing it removes a recurring source of false-positive `pytest -x -q` failures that mask real regressions during `/commit-proj` flows.

## Workflow
1. **Verify the issue is still relevant.** Re-read the fragment from `origin/main`. Reproduce locally:
   ```bash
   git fetch origin main --quiet
   # In a shell where .env (with R2_BUCKET set) has been sourced and FILINGS_REVIEWER_ALLOW_PROD_WRITES is NOT set:
   pytest tests/integration/extraction_v2/test_e2e_pipeline.py tests/integration/test_full_page_ocr_pipeline.py -x -q --tb=short
   ```
   Expect ~10 `Refusing R2 write` failures matching the fragment's list. If reproduction shows a different failure mode, stop and re-scope before planning. If all 10 already pass on clean main (e.g. someone already shipped a fix), abort and produce a fragment-only closure PR per `project_fragment_only_closure_pattern`.

2. **Plan mode.** Use plan mode. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by global `Planning Rules` — at minimum, decide whether `.claude/rules/infrastructure.md` and `docs/development/CONTRIBUTING.md` need a "tests use LocalFilesystemStorage automatically" note.

3. **Worktree-first.** First step of implementation: `EnterWorktree fix/gh-262-r2-guard-test-fixture`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT:** confirm `LocalFilesystemStorage` is the right swap-in (read `src/infra/image_storage.py` for the `ImageStorage` interface and existing factory). Confirm the guard is keyed on `R2_BUCKET` + `FILINGS_REVIEWER_ALLOW_PROD_WRITES` and not some other env var. Confirm there isn't already a fixture pattern in `tests/conftest.py` you should extend instead of inventing a new one.
   - **SCOPE CHECK:** the fragment lists two options (test-side fix vs env-side documentation). Per the fragment, the **test-side fix is preferred**; default to that. If the user wants only documentation, surface that as a redirect before writing code.
   - **RULES COMPLIANCE:** the guard must remain functional in non-test contexts — do not weaken it globally. The fixture should only redirect storage for the duration of the test process. Never write a fix that disables the guard via env-var injection in CI; the guard's presence is what protects prod from CLI scripts.
   - **RISK ASSESSMENT:** other tests may depend on the prod guard firing (e.g. tests that assert it raises). Grep for `FILINGS_REVIEWER_ALLOW_PROD_WRITES` and `Refusing R2 write` across `tests/` before swapping the default. Any guard-asserting test must continue to use the real backend (or mock it explicitly).
   - **MINIMAL PATH:** an autouse fixture (or session-scoped fixture) in `tests/integration/conftest.py` that points the test process at `LocalFilesystemStorage` when `R2_BUCKET` is set but `FILINGS_REVIEWER_ALLOW_PROD_WRITES` is not. This avoids editing each test's body.

5. **Implementation** (test-side fix path):
   - Add a fixture (autouse on the relevant integration scope) in `tests/integration/conftest.py` that overrides image-storage creation to `LocalFilesystemStorage` for the duration of the test, when `R2_BUCKET` is set without `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1`. Document the override in a one-line comment near the fixture so future readers don't assume R2 is always disabled in tests.
   - If the fixture mechanism needs an injection point in `src/infra/image_storage.py` (e.g., a module-level factory the fixture can monkeypatch), make the smallest change there.
   - Confirm the fixture is **not** loaded for unit tests (`tests/unit/...`) and **does not** weaken the guard in the production code path.

6. **Tests.**
   - Re-run the 10 listed cases: `pytest tests/integration/extraction_v2/test_e2e_pipeline.py tests/integration/test_full_page_ocr_pipeline.py -x -q --tb=short`. All 10 must pass.
   - Run the broader integration suite to confirm no other tests now break (e.g., guard-assertion tests): `pytest tests/integration -x -q --tb=short`.
   - Add a test that asserts the guard still fires when `LocalFilesystemStorage` is **not** active and `FILINGS_REVIEWER_ALLOW_PROD_WRITES` is unset — this is the regression-protection for "we accidentally disabled the guard everywhere." A simple unit test in `tests/unit/infra/` exercising the guard branch directly is fine.
   - Pre-existing failures: per project `CLAUDE.md`, do not spend time fixing failures that predate this work. Confirm with `git stash && pytest <case> -x -q && git stash pop`.

7. **Update fragment status as part of the same PR.** Flip `status: open` → `resolved`, `autonomy: safe` (already), set `pr_refs: [<this PR #>]`, append a `### Resolution` section describing the fixture and which test files now pass cleanly under `R2_BUCKET` set + `FILINGS_REVIEWER_ALLOW_PROD_WRITES` unset. Per `feedback_known_issues_pr_refs_int_not_string`, write `- 285` not `- '#285'`. Per `feedback_known_issues_validator_optional_fields`, do not add frontmatter fields outside `{pr_refs, gh_issue, note}`.

8. **Commit + PR.** Use the **project-local** `/commit-proj` skill (Safe Commit + PR Skill) — **not** the global `/commit`. Run it from your worktree.

9. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. Fetch the actual head ref via `gh pr view --json headRefName` before any follow-up push.

## Out of scope (do NOT expand into)
- Modifying the prod-write guard's semantics in `src/infra/image_storage.py` beyond what is required to inject the test fixture. The guard must remain on for non-test code paths.
- Changing `R2_BUCKET` defaults or `.env` templates.
- The `pyproject.toml` / `CONTRIBUTING.md` documentation-only path (Option B in the fragment) unless the user explicitly redirects there.
- Any refactor of `LocalFilesystemStorage` or the storage interface.
- Concurrent in-flight work — do **not** touch:
  - `src/web/routes/review_unified.py`, `src/web/routes/api_unified.py`, `src/web/templates/unified_review.html` (legacy-089, in flight; PR #284 also touches these)
  - `scripts/export_image_training_data.py`, `scripts/retrain_image_triage.py`, `scripts/benchmark_vision.py`, `src/llm/vision_client.py`, `src/gold_standard/image_eval.py` (gh-196, in parallel)
  - `.claude/commands/commit-proj.md`, `scripts/validate_known_issues_fragments.py` (gh-258, in parallel)
  - `src/infra/db.py` (open PR #284)

## Memory references that apply
- `feedback_verify_issue_status` — verify on origin/main first
- `feedback_verify_auto_merge_after_commit` — verify auto-merge is set
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `feedback_known_issues_pr_refs_int_not_string` — `- 285`, not `- '#285'`
- `feedback_known_issues_validator_optional_fields` — don't add frontmatter fields outside the allowlist
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `project_render_env_invisible_to_git_audit` — Render env-group config is invisible to PR review; default new safety controls to code, not env. The R2 guard's strength comes from being in code — preserve that.
- `feedback_run_recovery_before_verification` — when removing or weakening masking scaffolding (e.g., guard-skipping fixtures), confirm the underlying state is clean before declaring success.
- `feedback_scan_adjacent_defensive_code` — pre-existing test scaffolding may already mask the issue (e.g., a conftest that sets `FILINGS_REVIEWER_ALLOW_PROD_WRITES=1` for CI). Grep for env-var setters in `tests/` and `.github/` before adding new ones.

## Return
The PR URL when done.

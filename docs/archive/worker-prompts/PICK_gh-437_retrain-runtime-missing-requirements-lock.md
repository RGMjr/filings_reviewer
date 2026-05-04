You are working gh-437: every UI-triggered "Update Image Classifier" retrain dies in ~40 seconds with `model_training_runs.error='retrain_subprocess_died_no_status'`. The new sklearn version check (#420 / gh-406) reads `/app/requirements.lock` at script startup, but that file is bind-mounted in the Dockerfile builder stage only and never `COPY`'d into the runtime image. `FileNotFoundError` fires before the script's run-id try/except can catch it, so the DB row never gets a meaningful error.

## Source of truth

- Fragment: `docs/known-issues/gh-437-retrain-runtime-missing-requirements-lock.md` (read fully from `origin/main` before planning).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules".
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
- Related context (read for shape, do not modify unless implementation requires):
  - `Dockerfile` (runtime stage, current COPY list)
  - `scripts/retrain_image_triage.py` (the version-check entry point and the run-id try/except)
  - `src/ml/retrain_runner.py` (the worker that emits `retrain_subprocess_died_no_status` after the 30s poll)
  - `src/web/routes/api_unified.py::trigger_image_classifier_retrain` (the queue-write entry point + concurrency / threshold gates + gh-392 stale-row sweep)
  - `requirements.lock` (the file you're going to start shipping)
  - `.claude/rules/web.md` "Image-classifier retrain endpoints" section (the documented contract)

## Status note (read first)

The fragment is **`open`, severity `high`** because the Update Image Classifier button is currently dead in prod for any user — every click produces the same 40-second failure. The previous reliability work (gh-391, gh-392, gh-400, gh-406) all shipped in the last 72 hours; this is a regression introduced by #420 (the sklearn version check) interacting with the Dockerfile's bind-mount-only requirements.lock pattern. None of the three other PRs are at fault on their own.

The `_FAIL_NO_STATUS_SQL` post-mortem in `src/ml/retrain_runner.py` is doing exactly what it should — flipping the row to `failed` instead of leaving it stuck — but its generic error string (`retrain_subprocess_died_no_status`) is opaque to operators. Part of this fix tightens that.

## Workflow

1. **Reproduce the failure first.** Don't just trust the fragment — verify the cause:
   ```bash
   git fetch origin main --quiet
   # Confirm requirements.lock is bind-mounted, not COPY'd:
   grep -n "requirements.lock" Dockerfile
   # Confirm the version check fires before the run-id try/except:
   grep -nE "check_sklearn_version|_read_pinned_sklearn_version|if args.run_id" scripts/retrain_image_triage.py
   ```
   Expected: a single `--mount=type=bind,source=requirements.lock` in Dockerfile builder; `check_sklearn_version()` called from `main()` BEFORE `if args.run_id:` opens its try/except.

   Optional belt-and-suspenders repro:
   ```bash
   docker build -t filings-reviewer-test .
   docker run --rm filings-reviewer-test test -f /app/requirements.lock || echo "CONFIRMED: requirements.lock missing from runtime image"
   ```

2. **Plan mode.** Use plan mode — this touches Dockerfile + a script that can't be unit-tested in isolation, and it ships to a critical operator-facing button. Run `/plan-review` before exiting plan mode. The plan must include the **Documentation** step required by global `Planning Rules` (likely `.claude/rules/web.md` retrain endpoint paragraph and possibly a one-line note in CLAUDE.md if the version-check behavior is documented there).

3. **Worktree-first.** First step of implementation: `EnterWorktree fix-gh-437-retrain-requirements-lock` (or `ccw fix-gh-437-retrain-requirements-lock` from the shell). The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT.** Verify each claim in the fragment against the live worktree:
     - Dockerfile bind-mount-not-COPY pattern (re-read the runtime stage; the COPY list should not include `requirements.lock`).
     - `check_sklearn_version()` called before `if args.run_id:` in `main()`.
     - `_FAIL_NO_STATUS_SQL` SQL string + 30s `poll_interval` math in `src/ml/retrain_runner.py`.
     - The `src/ml/retrain_runner.py` path may be different — find it via `grep -rln "retrain_subprocess_died_no_status" src/`. Don't assume the location; #424 might have placed it elsewhere.
   - **SCOPE CHECK.** This fragment names three layered fixes. **Do all three.** They are:
     1. Dockerfile `COPY` line (the actual unblocker).
     2. Move `check_sklearn_version()` inside the run-id try/except (so future startup failures get a meaningful DB error).
     3. `_read_pinned_sklearn_version()` catches `FileNotFoundError` and degrades to a warning (loud-but-not-fatal).
     They are complementary, not alternatives. Skipping any one leaves a future regression invisible. Do not expand beyond these three (no refactoring of the retrain script's structure, no new logging framework, no new env vars).
   - **RULES COMPLIANCE.** Re-read `CLAUDE.md` "Implementation Rules" — execute ONLY the three fixes above, do not address adjacent issues even if you spot them. If you spot an adjacent issue worth tracking, file a follow-up fragment per the project's gh-N convention (`gh issue create` first, then fragment file per `.claude/commands/commit-proj.md` step 9).
   - **RISK ASSESSMENT.** What could break:
     - The Dockerfile change adds ~30 KB to the runtime image. Negligible.
     - Moving `check_sklearn_version()` inside the try/except means a version-mismatch failure now writes a DB row instead of just exiting with traceback. The web UI's `retrain_running` flag will clear correctly on next page load (already handled by the existing failure path). Verify by reading the `_FAIL_NO_STATUS_SQL` site to make sure it doesn't double-write if the script does write its own failure row.
     - Adding the `FileNotFoundError` catch in `_read_pinned_sklearn_version()` means dev / CLI runs without `requirements.lock` in CWD will skip the check silently with a warning. That's the desired behavior; document the warning string in the fragment update so operators recognize it.
     - The Render `filings-onboarding-runner` worker rebuild is the deploy that actually fixes prod. Confirm `render.yaml` doesn't need a change — the worker uses the same Dockerfile.
   - **MINIMAL PATH.** Three small edits + one Dockerfile line + tests. No env-var changes, no schema changes, no new dependencies.
   - **WORKTREE CHECK.** Per global gate item 6: confirmed worktree-first as step 3 above.

5. **Implementation** (in this order):

   **5a. Dockerfile** — add to the runtime stage, near the existing COPY block:
   ```dockerfile
   # gh-437: required by scripts/retrain_image_triage.py's sklearn version check
   # (gh-406). Bind-mount in builder is not enough — the runtime image must
   # contain the file so the worker can compare installed sklearn against the
   # pinned version at script startup.
   COPY --chown=appuser:appuser requirements.lock ./requirements.lock
   ```

   **5b. `scripts/retrain_image_triage.py`** — make two changes:
   - Move `check_sklearn_version()` from before the `if args.run_id:` block to inside it. The new placement should be the first statement inside the try block, before `_orchestrate(args)`. Rationale in a one-line comment referencing gh-437.
   - In `_read_pinned_sklearn_version()`, wrap the `lock_path.read_text()` in a try/except that catches `FileNotFoundError`, logs a warning (`logger.warning("requirements.lock not present at %s — skipping sklearn version check (gh-437)", lock_path)`), and returns `None`. Then update `check_sklearn_version()` to no-op when the pinned version is `None`.

   **5c. Tests** — add to `tests/unit/scripts/test_retrain_image_triage.py` (create if missing):
   - `test_read_pinned_sklearn_version_returns_none_when_lock_file_missing`: tmp_path with no requirements.lock, expect None + warning log.
   - `test_check_sklearn_version_noop_when_pin_unknown`: monkeypatch `_read_pinned_sklearn_version` to return None, call `check_sklearn_version()`, assert no exception and no `sys.exit`.
   - `test_check_sklearn_version_in_run_id_branch_writes_failed_on_mismatch`: simulate the run-id flow with a wrong sklearn version, verify the DB UPDATE is called with `status='failed'` and the error string contains the version mismatch detail. Mock `_update_run_status` and `psycopg.connect` per the existing pattern in adjacent tests.

   **5d. Documentation update.** The `.claude/rules/web.md` "Retrain script writeback" paragraph mentions the post-mortem behavior — extend it to note that startup-time failures now write a meaningful `error` string (not the generic `retrain_subprocess_died_no_status`). One sentence is enough.

6. **Verification** (before commit):
   ```bash
   pytest tests/unit/scripts/test_retrain_image_triage.py -v
   pytest tests/unit/web/test_models_retrain.py -v   # existing tests should stay green
   docker build -t filings-reviewer-test .
   docker run --rm filings-reviewer-test test -f /app/requirements.lock && echo "FIXED: requirements.lock present in runtime"
   ```
   Expected: all tests pass, file exists in runtime image.

7. **Commit + PR** via `/commit-proj`. The skill auto-branches from main, runs the pre-commit framework (ruff + extraction-guard + fragment validator), pushes, opens a PR, queues auto-merge. The PR description should reference gh-437 explicitly and note that this is a deploy-blocked-on-merge fix (the worker container rebuilds from the Dockerfile on the next deploy, so the fix takes effect when GitHub squash-merges + Render redeploys, not earlier).

8. **Post-merge verification** (do not skip — this is the closing-the-loop step):
   - Wait for Render's `filings-onboarding-runner` deploy to complete (Render dashboard → service → Events).
   - Trigger a retrain via the Update Image Classifier button on `/v2/review/stats` (or POST directly with curl + `FILINGS_API_KEY` if you don't have a browser session).
   - Poll the status endpoint until `status='succeeded'`.
   - Verify `models/image_relevance/latest_run_id.txt` exists in R2 and matches the run id.
   - Verify `predict_relevance` now returns non-None for sample queue rows by hitting the model-score sort: `https://filings-reviewer.onrender.com/v2/review/<filing>?tab=images&image_sort=model_score` should show score badges.
   - Update gh-437 fragment status to `resolved`, add `pr_refs: [<PR#>]` (per memory: list of ints, no `#` prefix).

## Notes for the implementer

- Do NOT bypass the version check entirely (e.g., delete it). The whole point of #420 was to prevent silent unpickle failures from sklearn version drift. The fix preserves the check; it just makes it possible to run.
- Do NOT add a `requirements.lock` to `.dockerignore`-style allowlists if any exist. The file should be free to enter the runtime image.
- The `data/image_model/relevance_model.joblib` currently committed is the 808-sample stale model (per gh-428). After this fix unblocks the button, the next retrain will produce a 1499-sample model and write it to R2. Do NOT in this PR also try to refresh the committed joblib — that's a follow-up task tracked in gh-428, and conflating them muddies the PR scope.
- The retrain runs on `filings-onboarding-runner` (per #424) — it's the same worker that handles ingest, not a dedicated `filings-retrain-runner`. Don't be confused by the name.
- When you trigger the post-merge verification retrain, you'll be the first person to populate `models/image_relevance/latest_run_id.txt` in R2. The model-score sort will start producing real reordering for the first time in prod after this fix lands.

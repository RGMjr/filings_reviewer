You are working gh-406: `retrain_image_triage.py` should enforce sklearn version match against requirements.lock.

## Source of truth
- Fragment: `docs/known-issues/gh-406-retrain-sklearn-version-check.md` (read in full)
- CLAUDE.md (project root) — read fully; obey Implementation Rules and Pre-Implementation Gate
- Global CLAUDE.md (~/.claude/CLAUDE.md) — read fully; especially Implementation Rules and Planning Rules
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully
- `.claude/rules/scripts.md` (if it exists) for script-testing conventions

## Background already established (do not re-litigate without new evidence)

A pre-investigation found:

- **The pin lives in `requirements.lock:223`**: `scikit-learn==1.8.0`. `requirements.txt:64` is loose (`scikit-learn>=1.4.0`); the lock is the production source of truth.
- **`scripts/retrain_image_triage.py` is an orchestrator.** It does NOT import sklearn itself — it spawns `scripts/export_image_training_data.py` then `scripts/train_image_relevance_model.py` as subprocesses (the latter is where joblib serialization happens). The fragment still asks for the guard at the top of the orchestrator (fail-fast before the export step burns time).
- **The silent-failure path is real.** `src/shared/image_features.py::predict_relevance` (lines 82-100) and `_load_model` (lines 50-79) swallow joblib load errors and return `None`. Callers treat `None` as "model absent → fall back to heuristic," so a version-mismatched joblib produces no observable error in production.
- **The web endpoint** `POST /api/v2/models/image-classifier/retrain` (handler `trigger_image_classifier_retrain` at `src/web/routes/api_unified.py:1222-1323`) spawns the orchestrator via `_spawn_retrain_runner` (lines 1178-1218). The script-level guard catches this path because the subprocess inherits the same Python venv. **No web-route change is needed.**
- **gh-400 (retrain queue + worker pattern)** is an untracked fragment in the working tree describing a future move to a background worker queue. The guard placement does not change after gh-400 lands — the script still runs as a subprocess from the worker. Use `sys.exit(1)`, not `raise`, so the wrapper captures the exit code and writes `model_training_runs.error`.
- **Existing pattern to mirror:** `scripts/check_pg_client_version.py` (lines 34-67) — defines a reusable `check_pg_client_version()` with a clear error message and `sys.exit(1)` on mismatch. Use the same shape (define a top-level helper in the orchestrator script; do not extract to a shared module — premature abstraction with one caller).
- **Existing tests:** `tests/unit/web/test_models_retrain.py` only tests the web endpoint with `subprocess.Popen` mocked; the orchestrator script itself has zero direct test coverage. The `importlib`-loading pattern at `tests/integration/test_onboard_tickers_cli.py` is the project precedent for testing CLI scripts.

## Recommended fix

**Add the guard at the top of `main()` in `scripts/retrain_image_triage.py`.** Read the pinned version from `requirements.lock` at runtime (single source of truth — pin can change without forgetting to update the script). Provide an opt-out flag for local experimentation as the fragment suggests.

### Files to modify

1. **`scripts/retrain_image_triage.py`** (~30 lines added):

   - Add two top-level helpers (place near the existing imports, before `main()`):
     ```python
     def _read_pinned_sklearn_version() -> str:
         """Read the sklearn pin from requirements.lock (single source of truth)."""
         lock_path = Path(__file__).resolve().parent.parent / "requirements.lock"
         for line in lock_path.read_text().splitlines():
             stripped = line.strip()
             if stripped.startswith("scikit-learn==") and not stripped.startswith("#"):
                 return stripped.split("==", 1)[1].split()[0]
         raise RuntimeError(
             f"scikit-learn pin not found in {lock_path}. "
             "Refusing to retrain without a known target version."
         )

     def check_sklearn_version(*, allow_mismatch: bool = False) -> None:
         """Exit with a clear error if local sklearn != requirements.lock pin."""
         import sklearn
         pinned = _read_pinned_sklearn_version()
         installed = sklearn.__version__
         if installed == pinned:
             return
         msg = (
             f"sklearn version mismatch: requirements.lock pins {pinned}, "
             f"local venv has {installed}. A version-mismatched joblib "
             "unpickles silently into None on Render — predict_relevance "
             "returns None, no error is raised. Run: "
             "uv pip install -r requirements.lock"
         )
         if allow_mismatch:
             logger.warning("%s (continuing because --allow-version-mismatch was set)", msg)
             return
         logger.error(msg)
         sys.exit(1)
     ```

   - Add the argparse flag (in the existing argparse block ~lines 157-217):
     ```python
     parser.add_argument(
         "--allow-version-mismatch",
         action="store_true",
         help="Skip the sklearn version guard. For local experimentation only — "
              "produced joblib will not load on Render.",
     )
     ```

   - Call the guard at the top of `main()` (after `configure_logging()`, before `database_url` validation):
     ```python
     check_sklearn_version(allow_mismatch=args.allow_version_mismatch)
     ```

   Do NOT add the guard to `train_image_relevance_model.py` — that's a scope expansion. The orchestrator covers all production invocation paths (CLI, web endpoint, future worker queue). If you spot operators running the train script directly, file a follow-up fragment.

2. **`tests/unit/scripts/test_retrain_image_triage.py`** (new file, ~70 lines):

   Follow the importlib pattern from `tests/integration/test_onboard_tickers_cli.py`. Cover:

   - `_read_pinned_sklearn_version()` returns the version from `requirements.lock` (sanity).
   - `check_sklearn_version()` raises `SystemExit(1)` when `sklearn.__version__` is monkeypatched to a wrong value.
   - `check_sklearn_version()` returns silently when `sklearn.__version__` matches.
   - `check_sklearn_version(allow_mismatch=True)` does NOT exit even on mismatch (logs a warning).

   Use `monkeypatch.setattr("sklearn.__version__", "0.0.0-mock")` to inject a fake version. Capture log output with `caplog` to assert the warning fires under `--allow-version-mismatch`.

   Place under `tests/unit/scripts/` — create the directory + `__init__.py` if absent (mirror `tests/unit/web/`).

3. **`docs/known-issues/gh-406-retrain-sklearn-version-check.md`** — apply `project_fragment_only_closure_pattern` inline:
   - `status: open` → `status: resolved`
   - `autonomy: skip` → `autonomy: n/a`
   - Add `pr_refs:` with this PR's number after `/commit-proj` returns it
   - Append `### Resolution` section: name the helpers added, the argparse flag, the test file, and note that gh-400 (worker queue) does not invalidate the placement.

## Workflow

1. **Verify the issue is still relevant.** From a fresh `ccw` worktree:
   ```bash
   grep -n "sklearn" scripts/retrain_image_triage.py
   grep -n "scikit-learn" requirements.lock
   ```
   Confirm: no existing sklearn import / version guard in the script; the pin is still `scikit-learn==1.8.0` (or whatever current). If a guard already exists or the pin moved out of `requirements.lock`, STOP and reassess.

2. **Plan mode.** Use plan mode for this change — it touches 3 files and adds a new helper/test. Run `/plan-review` before exiting plan mode.

3. **Worktree-first.** First implementation step: `EnterWorktree fix/gh-406-sklearn-version-check`. The PreToolUse hook denies HEAD-moving git ops in the primary tree.

4. **Pre-Implementation Gate** (per global CLAUDE.md, required for 3+ files). Show the completed checklist (assumptions audit, scope check, rules compliance, risk assessment, minimal path, worktree confirmation) and get user approval before writing code.

5. **Implementation** — see "Files to modify" above.

6. **Tests.** Per project CLAUDE.md, run `pytest -x -q --tb=short`. Specifically verify:
   ```bash
   pytest tests/unit/scripts/test_retrain_image_triage.py -v
   ```
   Manual smoke-test the script's guard:
   ```bash
   # Should pass with current venv (assuming you ran `uv pip install -r requirements.lock`)
   python3 scripts/retrain_image_triage.py --dry-run

   # Verify the guard message format by temporarily faking a mismatch (revert before commit):
   python3 -c "import sklearn; sklearn.__version__='0.0.0'; exec(open('scripts/retrain_image_triage.py').read().replace('main()', 'check_sklearn_version()'))"
   ```

7. **Commit + PR via `/commit-proj`** (project-local). The skill handles the pre-commit framework, fragment validation, and required-checks recital.

8. **Verify auto-merge.** After `/commit-proj` returns, run `gh pr view --json autoMergeRequest`. If unset, run `gh pr merge <PR#> --auto --squash`. (Project rule — auto-merge is sometimes silently dropped on the first push.)

## Out of scope (do NOT expand into)

- **Do not add the guard to `train_image_relevance_model.py` or `export_image_training_data.py`.** The orchestrator covers all production paths. File a follow-up fragment if you find a path that bypasses the orchestrator.
- **Do not extract `check_sklearn_version` to a shared module.** One caller, premature abstraction. The `scripts/check_pg_client_version.py` precedent is also a single-script helper.
- **Do not change `predict_relevance()` or `_load_model()` to raise on version mismatch.** That's a separate fix (the silent-None behavior is by design for "model absent" — disambiguating "absent vs. broken" is a distinct issue worth its own fragment if you care).
- **Do not edit `requirements.lock` or `requirements.txt`.** The pin is whatever the project chose; the guard reads it.
- **Do not bump the loose pin in `requirements.txt`.** Out of scope and risks downstream churn.
- **Do not tighten the `--allow-version-mismatch` opt-out** with extra flags or env vars — keep it a single boolean.
- **Do not modify `src/web/routes/api_unified.py`** — the script-level guard catches the web-spawned path.
- **No concurrent worktrees touch this file** at time of plan-write (`gh pr list --state open --search retrain` returned empty), but re-verify before commit.

## Memory references that apply

- `feedback_verify_issue_status` — verify no guard exists yet on origin/main before adding one
- `feedback_subagent_midstream_stops` — if you delegate to a subagent and it returns truncated, dispatch a tightly-scoped wrap-up pinned to the existing worktree
- `project_fragment_only_closure_pattern` — fragment frontmatter flip + Resolution section in the same PR
- `feedback_reread_worker_prompt_line_refs` — line refs in this prompt freeze plan-time file state; re-verify against worktree HEAD before applying edits (relevant: `requirements.lock:223`, `scripts/retrain_image_triage.py` lines 157-217 / 256-308 / 311-312, `src/web/routes/api_unified.py:1178-1323`)
- `feedback_check_existing_fragment_before_create` — before drafting a new follow-up fragment for any out-of-scope finding, grep `gh_issue:` in `docs/known-issues/` to avoid duplicates

## Return

The PR URL when done.

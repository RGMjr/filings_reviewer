You are working gh-426: `scripts/export_image_training_data.py` and `scripts/train_image_relevance_model.py` are independently runnable. `scripts/retrain_image_triage.py` chains them, but operators can (and have) re-run the export alone, leaving `data/image_model/training_data.csv` regenerated while `relevance_model.joblib` reflects the prior CSV. Currently benign because the prod loader reads R2 (gh-391) — this is a dev-side staleness bug. Becomes silent staleness in prod the moment anyone bypasses the chained workflow.

## Source of truth

- Fragment: `docs/known-issues/gh-426-export-without-retrain-stale-model.md` (read fully from `origin/main` before planning).
- `CLAUDE.md` (project root) — read fully; obey **Implementation Rules** and **Pre-Implementation Gate**.
- Global `~/.claude/CLAUDE.md` — read; especially "Implementation Rules" and "Planning Rules".
- Project memory at `~/.claude/projects/-Users-rgmarkey-CMASB-Coding-filings-reviewer/memory/MEMORY.md` — read fully and apply.
- Related context (read for shape, do not modify unless implementation requires):
  - `scripts/retrain_image_triage.py` (the chaining script — it already does the right thing; the gap is operators bypassing it)
  - `scripts/export_image_training_data.py` (what to harden — emits stale CSVs unilaterally)
  - `scripts/train_image_relevance_model.py` (consumes the CSV blindly)
  - `data/image_model/` (where the artifacts live; the CSV / joblib pair that drifts)
  - `docs/analysis/gh-405-chart-classifier-overflag-audit.md` (the audit that surfaced this — read the "Side findings" section)

## Workflow

1. **Reproduce the staleness scenario.** Verify the gap is real:
   ```bash
   git fetch origin main --quiet
   wc -l data/image_model/training_data.csv  # current row count
   python3 -c "import joblib; m = joblib.load('data/image_model/relevance_model.joblib'); print('Trained on:', m.named_steps['clf'].n_features_in_, 'features (proxy for sample count via report)')"
   cat data/image_model/model_report.txt | head -10  # actual training row count
   ```
   If the CSV row count and the joblib-report row count don't match, the staleness is reproduced. Document the delta in the PR description.

2. **Plan mode.** Use plan mode — touches a script that operators run by hand and the project's already-shipped retrain pipeline. Run `/plan-review` before exiting. The plan must include the **Documentation** step: a one-line note in `docs/operations/` if there's a runbook for retraining, OR an inline doc string update in `scripts/export_image_training_data.py` that warns operators against running it alone.

3. **Worktree-first.** First step of implementation: `EnterWorktree gh-426-export-retrain-sync`.

4. **Pre-Implementation Gate** (per global `CLAUDE.md`).
   - **ASSUMPTION AUDIT.** Verify:
     - `export_image_training_data.py` and `train_image_relevance_model.py` are still independently invokable (no shared lock, no cross-script state check).
     - `retrain_image_triage.py` chains them in the documented order.
     - `data/image_model/` is the canonical local landing site (post-gh-391 the prod path is R2; this is dev-only hygiene).
   - **SCOPE CHECK.** The fragment's "Next Steps" lists three options. Pick ONE based on what's least invasive and most likely to actually prevent the failure mode:
     - **Option A — Sidecar checksum + fail-fast on load.** `train_image_relevance_model.py` writes the input CSV's sha256 into a sidecar file alongside the joblib. The training-time check in `image_features._load_model` (or a new wrapper) recomputes against the on-disk CSV at startup and refuses to load if they don't match. Strongest guarantee, most code.
     - **Option B — Chain export into retrain by default with `--export-only` escape.** `export_image_training_data.py` becomes a thin wrapper that prints a warning and points at `retrain_image_triage.py`; the existing internal logic moves to a `_run_export()` helper that `retrain_image_triage.py` imports and calls. Operators wanting the old behavior pass `--export-only`. Behavioral nudge.
     - **Option C — Loud trailing warning at end of export step.** `export_image_training_data.py` prints a multi-line warning at the end pointing at the next required command. Cheapest, weakest guarantee.
     **Recommendation: Option C** — it's a dev-only nudge (prod uses R2, the loader is robust per gh-419 once that ships); zero risk of breaking existing CLI workflows; one PR to write and review. If gh-426 reopens because operators ignore the warning, escalate to Option B (a deliberate behavioral shift). Option A is over-engineering for a non-prod hygiene issue.
   - **RULES COMPLIANCE.** Re-read CLAUDE.md "Implementation Rules" — execute ONLY the chosen option, do not silently combine multiple ones.
   - **RISK ASSESSMENT.** What could break:
     - Option C: nothing. The warning is purely additive output.
     - Option B: any CI / docs / harness referencing `python3 scripts/export_image_training_data.py` directly. Grep for it; update each call site to either chain through `retrain_image_triage.py` OR pass `--export-only`.
     - Option A: the sidecar check needs a clean upgrade path for existing R2 artifacts that don't have sidecars. Either skip the check on absent sidecars (degrades silently) or fail-fast (breaks prod until backfill). Both have caveats.
   - **MINIMAL PATH.** Option C is the minimal path. Stay there unless you have evidence operators are ignoring trailing warnings.

5. **Implementation (Option C — recommended):**

   **5a. `scripts/export_image_training_data.py`** — at the end of the script's `main()` function (or just before `sys.exit(0)`), print a multi-line warning to stderr:
   ```python
   print("\n" + "=" * 70, file=sys.stderr)
   print("WARNING: Export complete but model NOT retrained.", file=sys.stderr)
   print("If you intend to update data/image_model/relevance_model.joblib, run:", file=sys.stderr)
   print(f"  python3 scripts/retrain_image_triage.py --database-url ...", file=sys.stderr)
   print("Otherwise the on-disk CSV will be out of sync with the joblib (gh-426).", file=sys.stderr)
   print("=" * 70, file=sys.stderr)
   ```
   Skip the warning when invoked from inside `retrain_image_triage.py` — easiest signal is an env var the parent script sets:
   ```python
   if os.environ.get("RETRAIN_CHAINED") != "1":
       # ... print the warning
   ```
   And in `retrain_image_triage.py` set `os.environ["RETRAIN_CHAINED"] = "1"` before calling the export step.

   **5b. Documentation.** Add a one-line note at the top of `scripts/export_image_training_data.py` (module docstring): "If you intend to refresh the deployed model, use `scripts/retrain_image_triage.py` (which chains export + train); see gh-426."

6. **Verification:**
   - `python3 scripts/export_image_training_data.py --output /tmp/x.csv --source all --database-url "$TEST_DATABASE_URL"` — expect to see the warning at the end.
   - `python3 scripts/retrain_image_triage.py --database-url "$TEST_DATABASE_URL"` — expect NO warning (env var suppresses it).
   - `pytest -x -q` — confirm no test depends on the absence of the new stderr output.

7. **Commit + PR** via `/commit-proj`. PR description should reference gh-426. After merge: update the fragment to `status: resolved` with `pr_refs: [<PR#>]`.

## Notes for the implementer

- gh-426 was identified during the gh-405 audit. The discovered staleness gap (CSV had 1499 rows, joblib was the 808-row model) was the original symptom. After cba5e60f shipped via R2, the prod loader pulls the right artifact, so this is dev-hygiene only.
- The fragment's third option ("loud warning") is the right ship. The first ("sidecar checksum") is over-engineering for a dev-side issue. The second ("chain by default") changes existing operator workflows and risks breaking CI / docs / future scripts.
- If this fragment ever needs to graduate to Option B because operators are still hitting the staleness gap, file a follow-up `gh-N` rather than reopening gh-426.

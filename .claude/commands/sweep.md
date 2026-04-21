# Nightly Sweep — Manual Invoke Skill

**Purpose:** Run the KNOWN_ISSUES sweeper manually (same flow the Render cron runs nightly). Useful for ad-hoc backlog drains, testing changes to the selector, or verifying a classification change.

**When to use:**
- The user says "run the sweep", "drain the backlog", "sweep issue #N".
- Local verification before landing a sweeper change.

---

## Steps

1. **Pause-file check.** If `.claude/sweep.pause` exists, announce it and confirm with the user whether to proceed. If they say yes, do not delete the file — instead invoke the script with a `SWEEP_FORCE=1` environment override (documented in the runbook). The nightly cron stays paused.

2. **Dry-run selector.** Run:
   ```bash
   python3 scripts/known_issues_selector.py --dry-run
   ```
   Show the user the picks. Confirm before continuing if `--max` should be different or `--include-review` should be on.

3. **Pre-flight.** Confirm:
   - `claude` CLI available (`command -v claude`)
   - `gh` authenticated (`gh auth status`)
   - On `main` with clean tree (`git status`, `git rev-parse --abbrev-ref HEAD`)
   - `ANTHROPIC_API_KEY` set
   If any fails, stop and report.

4. **Invoke.** Run:
   ```bash
   bash scripts/run_nightly_sweep.sh
   ```
   Stream output to the user.

5. **Report.** Summarise: N merged, N awaiting, N abandoned. Link each PR. Link the digest file.

---

## Rules

- Never delete `.claude/sweep.pause` to run manually — use an env override instead.
- Never pass `--no-pr-dedupe` to the orchestrator (only to `known_issues_selector.py --dry-run` when offline).
- If the selector returns zero picks, do not run the orchestrator — report "nothing to sweep" and exit.
- The manual run writes to the same `.claude/sweep-digests/` path as the cron; expect one digest file per date.

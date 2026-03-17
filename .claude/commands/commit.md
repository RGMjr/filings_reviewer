# Safe Commit Skill

**Purpose:** Validate code quality before committing — catches broken imports, lint errors, and test failures before they land.

**When to use:** Any time the user asks to commit changes.

---

## Steps

1. **Lint check** — Run `ruff check src/ tests/` and fix any errors before proceeding. Do NOT skip this if there are violations.

2. **Full test suite** — Run `pytest -x -q`. All tests must pass. If any fail, diagnose the root cause, fix it, then re-run. Repeat until all pass in a single run.

3. **Doc freshness checks** — After pytest passes:
   - If the pytest output shows a coverage percentage different from the one in `CLAUDE.md` (currently "87%"), update `CLAUDE.md` to match and stage the file.
   - If `docs/KNOWN_ISSUES.md` is staged, update its "Last Updated" date to today's date and re-stage it.
   - Check whether the staged changes affect anything documented in `CLAUDE.md` or `docs/` (e.g., adding/removing a CLI command, renaming a `src/` module, changing a route). If so, flag the specific discrepancy to the user and ask whether to update docs before committing.
   - If `docs/PROJECT_TASK_INVENTORY.md` "Last Verified" date is >30 days old, warn the user and suggest running `/doc-audit`.
   - Stage any doc fixes made in this step.

4. **Show staged diff** — Run `git diff --cached --stat` and show the user what will be committed.

5. **Confirm commit message** — Ask the user for the commit message. Wait for explicit confirmation before committing.

6. **Commit** — Run `git commit` with the confirmed message. Use a heredoc for multi-line messages.

7. **Push** — Run `git push`. If it fails, report the error and stop.

---

## Rules

- Never commit with failing tests.
- Never commit with ruff errors (warnings are acceptable).
- Never amend an existing commit unless the user explicitly asks to amend.
- If `git add` has not been run yet, ask the user which files to stage — do NOT run `git add -A` or `git add .` without explicit instruction.
- Always push after a successful commit. If the push fails, report the error and stop — do not retry silently.
- Doc auto-fixes are limited to deterministic values (coverage percentage, dates). Anything requiring judgment must be flagged to the user, not silently changed.

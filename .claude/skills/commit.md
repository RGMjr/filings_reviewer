# Safe Commit Skill

**Purpose:** Validate code quality before committing — catches broken imports, lint errors, and test failures before they land.

**When to use:** Any time the user asks to commit changes.

---

## Steps

1. **Lint check** — Run `ruff check src/ tests/` and fix any errors before proceeding. Do NOT skip this if there are violations.

2. **Full test suite** — Run `pytest -x -q`. All tests must pass. If any fail, diagnose the root cause, fix it, then re-run. Repeat until all pass in a single run.

3. **Show staged diff** — Run `git diff --cached --stat` and show the user what will be committed.

4. **Confirm commit message** — Ask the user for the commit message. Wait for explicit confirmation before committing.

5. **Commit** — Run `git commit` with the confirmed message. Use a heredoc for multi-line messages.

---

## Rules

- Never commit with failing tests.
- Never commit with ruff errors (warnings are acceptable).
- Never amend an existing commit unless the user explicitly asks to amend.
- If `git add` has not been run yet, ask the user which files to stage — do NOT run `git add -A` or `git add .` without explicit instruction.

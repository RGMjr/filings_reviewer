# Safe Commit Skill

**Purpose:** Validate code quality before committing — catches broken imports, lint errors, and test failures before they land.

**When to use:** Any time the user asks to commit changes.

---

## Steps

1. **Stage files** — Determine what to commit using three-tier logic:

   - **Session files exist:** Identify all files edited or created by Claude during this conversation (via Edit/Write tool calls). Cross-reference with `git status --porcelain` to confirm they have uncommitted changes. Auto-stage these with `git add <file1> <file2> ...` — no user confirmation needed. Do NOT auto-stage files with uncommitted changes that were not touched in this session.
   - **No session files, but pre-existing changes exist:** Run `git status --short`, show the output to the user, ask which files to stage, and wait for explicit confirmation before proceeding.
   - **Nothing to commit:** Report "No changes to commit" and stop.

2. **Lint check** — Check staged files (`git diff --cached --name-only`). If no code files are staged (i.e., no files under `src/`, `tests/`, `scripts/`, `config/`, `sql/`, and none of `pyproject.toml` or `requirements.txt`), skip lint with a note. Otherwise run `ruff check src/ tests/` and fix any errors before proceeding. Do NOT skip this if there are violations.

3. **Full test suite** — If no code files are staged (same definition as step 2), skip tests with a note. Otherwise run `pytest -x -q`. All tests must pass. If any fail, diagnose the root cause, fix it, then re-run. Repeat until all pass in a single run.

4. **Doc freshness checks** — After pytest passes:
   - If pytest was run and its output shows a coverage percentage different from the one in `CLAUDE.md` (currently "87%"), update `CLAUDE.md` to match and stage the file.
   - If `docs/KNOWN_ISSUES.md` is staged, update its "Last Updated" date to today's date and re-stage it.
   - Check whether the staged changes affect anything documented in `CLAUDE.md` or `docs/` (e.g., adding/removing a CLI command, renaming a `src/` module, changing a route). If so, flag the specific discrepancy to the user and ask whether to update docs before committing.
   - If `docs/PROJECT_TASK_INVENTORY.md` "Last Verified" date is >30 days old, warn the user and suggest running `/doc-audit`.
   - Stage any doc fixes made in this step.

5. **Show staged diff** — Run `git diff --cached --stat` and show the user what will be committed.

6. **Generate commit message and commit** — Analyze `git diff --cached` and the staged file list to generate a message:
   - Follow conventional commit format: `type: concise description` (subject line ≤72 chars)
   - Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`
   - If a ticket/issue reference is apparent from the branch name or diff context, include it in parens, e.g. `feat: add X (GR-16)`
   - Add a body (blank line + detail) only when the diff spans multiple distinct concerns
   - Use the generated message directly — no confirmation step. Run `git commit` with the message using a heredoc for multi-line messages.

7. **Push** — Run `git push`. If it fails, report the error and stop.

---

## Rules

- Never commit with failing tests.
- Never commit with ruff errors (warnings are acceptable).
- Never amend an existing commit unless the user explicitly asks to amend.
- Auto-stage session files (files edited or created by Claude in this conversation) without asking. Never auto-stage files not touched in this session — always ask first for pre-existing changes.
- Never use `git add -A` or `git add .`. Always stage specific files by name.
- Auto-commit using the generated message — no confirmation step needed.
- Always push after a successful commit. If the push fails, report the error and stop — do not retry silently.
- If no session files exist, show pre-existing changes and ask the user which to stage before proceeding.
- Doc auto-fixes are limited to deterministic values (coverage percentage, dates). Anything requiring judgment must be flagged to the user, not silently changed.

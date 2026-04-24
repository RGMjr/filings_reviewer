# Safe Commit + PR Skill (project-local)

**Purpose:** Gate code quality before commit (lint, tests, doc-freshness, known-issues triage), then branch + commit + push + open a PR + enable auto-merge. `main` is protected server-side; this skill matches the local flow to the remote contract.

**When to use:** Any time the user asks to commit changes.

---

## Steps

1. **Branch preflight.** Run `git branch --show-current`.
   - **If on `main` or `master`:** derive a new branch name from the staged diff.
     - Type: conventional-commit type inferred from the diff (`feat`/`fix`/`refactor`/`chore`/`docs`/`test`).
     - Slug: 3–6 word kebab-case summary of the change (e.g., `pr-workflow-enforcement`).
     - Branch: `claude/<type>-<slug>` (fall back to `claude/$(date +%Y%m%d)-$(git rev-parse --short HEAD)` if inference is uncertain).
     - **Collision check:** if `git show-ref --verify --quiet "refs/heads/<branch>"` returns true, append `-HHMM` (current-minute timestamp) so the rename is obviously collision-avoidance and survives multi-collision per day. If the suffixed name also collides (vanishingly rare), fail fast with a clear message.
     - Run `git checkout -b <branch>` and announce the branch name in one line.
   - **Otherwise:** stay on the current branch and continue.

2. **Pre-commit framework check.** Run `test -x .git/hooks/pre-commit` (the `pre-commit` framework installs an executable there). If missing, run `make hooks-install` and announce. Never symlink `scripts/pre-commit-extraction-guard.sh` into `.git/hooks/pre-commit` directly — it would clobber ruff / ruff-format. The guard is registered as a `local` hook in `.pre-commit-config.yaml` (id `extraction-guard`).

3. **Doc update check.** Review session changes and determine whether docs need updating. Skip if session changes are narrow. Otherwise apply targeted checks:

   | If the session touched... | Check and update... |
   |---|---|
   | New script or CLI command | `CLAUDE.md` commands section, `docs/README.md` |
   | New or renamed `src/` module | Architecture docs (`docs/architecture/`) |
   | New or changed API route | `docs/HUMAN_REVIEW_SYSTEM.md` or relevant route doc |
   | New env var | `.env.template` reference in `CLAUDE.md` |
   | New DB migration or schema change | `CLAUDE.md` database section, `docs/architecture/` |
   | Changed workflow or pipeline stage | `CLAUDE.md` pipeline description, relevant `docs/` file |

   For each implicated doc: read, compare against current code, update only what is factually wrong or missing. Flag editorial judgment calls to the user.

4. **Preserve pre-existing staging.** Run `git diff --cached --name-only`; capture already-staged files. Unstage with `git restore --staged <files>`. After the commit (step 12), re-stage them to restore index state.

5. **Stage files** — three-tier logic:
   - **Session files exist:** Identify all files edited/created by Claude this conversation (via Edit/Write tool calls), including any doc files updated in step 3. Cross-reference with `git status --porcelain` to confirm uncommitted. Auto-stage with `git add <files>` — no user confirmation. Do NOT auto-stage files with uncommitted changes that were not touched in this session.
   - **No session files, but pre-existing changes exist:** Run `git status --short`, show it to the user, ask which to stage, wait for explicit confirmation.
   - **Nothing to commit:** Report "No changes to commit" and stop.

6. **Lint check.** Check staged files (`git diff --cached --name-only`). If no code files are staged (`src/`, `tests/`, `scripts/`, `config/`, `sql/`, `pyproject.toml`, `requirements.txt`), skip with a note. Otherwise `ruff check src/ tests/` and fix any errors.

7. **Full test suite.** If no code files staged, skip with a note. Otherwise `pytest -x -q`. All must pass. Diagnose root cause on failures, fix, re-run until green in a single run.

8. **Doc freshness.** After pytest passes:
   - If pytest output shows a coverage percentage different from `CLAUDE.md` (currently "87%"), update and stage.
   - If `docs/PROJECT_TASK_INVENTORY.md` "Last Verified" date is >30 days old, warn and suggest `/doc-audit`.
   - Stage any fixes made here.

9. **Out-of-scope issue triage.** Review the session for issues that surfaced but were NOT addressed by this commit, and recommend which merit filing as fragment files under `docs/known-issues/`.

   **9a. Pre-flight guard.** If any `docs/known-issues/` fragment already has pre-existing uncommitted edits (staged or unstaged), stop and tell the user to commit those separately first.

   **9b. Enumerate candidates.** Consider every issue that surfaced but was not fixed:
   - Bugs/incorrect behavior observed but deliberately not fixed
   - Missing test coverage noticed and deferred
   - Code smells, dead code, tech debt flagged during exploration
   - Brittle patterns or fragile tests encountered
   - Follow-up work explicitly deferred ("let's handle X later", "out of scope")
   - Unexpected behavior in adjacent code paths surfaced while debugging

   Filter out:
   - Already tracked in `docs/known-issues/` fragments
   - Items the user told you to forget or decline to track
   - Ephemeral observations (test timing variance, comment typos)
   - Style preferences with no behavioral impact

   **9c. Classify.** Assign `FILE` or `SKIP` with a one-line rationale per item. Propose severity (high/medium/low) for `FILE` items.

   **9d. Present recommendations.** Default action is to file every `FILE`-recommended item. If no candidates, state "No out-of-scope issues surfaced this session" and proceed. Otherwise output:

   ```
   Out-of-scope issues surfaced this session. My recommendations:

   TO FILE:
   1. [Title] — Severity: [level]. Rationale: [why]
   2. ...

   TO SKIP:
   A. [Title]. Rationale: [why]
   B. ...

   Proceeding with filing items 1–[N] unless you say otherwise. Reply "approve" / "all" to accept, "none" to skip all, or list changes.
   ```

   **9e. Act.** "approve"/"all"/silent → file all `TO FILE`. "none"/"skip" → file nothing. Anything else → apply user edits, confirm revised list, file.

   **9f. Write fragment files.** For each item:
   - Find the highest existing id: `{ ls docs/known-issues/legacy-*.md docs/known-issues/gh-*.md 2>/dev/null; git ls-tree --name-only origin/main docs/known-issues/ 2>/dev/null; } | grep -oE '(legacy|gh)-[0-9]+' | grep -oE '[0-9]+' | sort -n | tail -1`. Next id = that + 1. (Union of local files and `origin/main` prevents collisions when multiple branches are in flight.)
   - Create `docs/known-issues/legacy-NNN-<kebab-slug>.md` with this exact structure:
     ```yaml
     ---
     id: NNN
     source: legacy
     slug: <kebab-case-slug>
     title: <Title>
     status: open
     severity: <high|medium|low>
     autonomy: skip  # default for new issues — reclassify after triage
     estimated: —    # — if unknown
     touches: []     # list of globs; required before sweeper will pick it up
     discovered: <today's date YYYY-MM-DD>
     updated: <today's date YYYY-MM-DD>
     note: <short one-line actionable summary>
     ---

     ### Problem

     <1–3 sentences: what was observed>

     ### Next Steps

     - <1–3 bullets: what would fix it>
     ```
   - Do NOT hand-edit `docs/KNOWN_ISSUES.md` — it is auto-generated.
   - Do NOT stage the fragment yet — it's a separate follow-up commit (step 13).

10. **Show staged diff.** Run `git diff --cached --stat`.

11. **Generate commit message and commit.** From `git diff --cached` + staged files:
    - Conventional commit: `type: concise description` (subject ≤72 chars)
    - Types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`
    - If a ticket/issue reference is apparent, include it in parens: `feat: add X (GR-16)`
    - Add a body (blank line + detail) only when the diff spans multiple distinct concerns
    - Use the generated message directly — no confirmation. Run `git commit` via heredoc for multi-line messages.

12. **Restore pre-existing staging.** Re-stage files that were unstaged in step 4.

13. **Known-issues follow-up commit.** Only if step 9 produced new fragment files under `docs/known-issues/`:
    - Run `python3 scripts/regenerate_known_issues.py` to update the rollup.
    - `git add docs/known-issues/legacy-NNN-<slug>.md docs/KNOWN_ISSUES.md` (fragment + regenerated rollup only).
    - Commit: `docs(known-issues): log issue(s) #N[, #M] — [descriptor]` (matches commits `87b54f7`, `e96b6fb`).
    - Do NOT push yet — step 14 pushes both commits together.

14. **Push the branch.** `git push -u origin "$(git branch --show-current)"`. If the push fails (e.g., pre-push hook rejects because of a test failure): report the error verbatim and stop. Do NOT retry silently, do NOT use `--no-verify`, do NOT push to any other branch.

15. **Open or reuse PR.**
    - `gh pr view --json number,state,url 2>/dev/null` — capture the JSON.
    - If `state == OPEN`: skip create; reuse the existing PR. Report the URL.
    - Otherwise: `gh pr create --fill` (auto-title from commit subject, auto-body from commit body + PR template). Capture the URL.
    - On `gh` failure (auth, rate-limit, etc.): report the exact error and stop. Do NOT fall back to any other form of merge.

16. **Enable auto-merge.** `gh pr merge --auto --squash` (idempotent — no-op if already enabled). `--squash` keeps main's history linear, matching the repo's existing pattern. Never use `--admin`.

17. **Conflict guard.** After enabling auto-merge, wait 5 seconds for GitHub to compute merge status, then check:
    ```
    gh pr view --json mergeable,mergeStateStatus
    ```
    - If `mergeStateStatus` is `DIRTY`: run `gh pr update-branch` (merges `main` into the PR branch). If it exits non-zero (real content conflict), warn: "Branch is DIRTY and update-branch failed — manual conflict resolution required."
    - Any other status (`BLOCKED`, `CLEAN`, `UNKNOWN`): no action.

18. **Report.** Final one-line summary to the user:
    ```
    PR #<n> opened/updated: <url>. Auto-merge enabled (squash). Waits on: Lint, Unit Tests, Vulnerability Scan, Integration Tests, UI E2E (Playwright). Run /ci-fix if checks go red.
    ```

---

## Rules

- Never commit with failing tests.
- Never commit with ruff errors (warnings are acceptable).
- Never amend an existing commit unless the user explicitly asks.
- Auto-stage session files; never auto-stage files not touched this session (always ask first for pre-existing changes).
- Never use `git add -A` or `git add .` — always stage specific files by name.
- Auto-commit using the generated message — no confirmation.
- **Never push directly to `main`.** Step 1 branches off main; if for any reason the branch is still `main` when step 14 runs, stop and report.
- **Never `--force` push. Never `--no-verify`. Never `gh pr merge --admin`.**
- If a PR already exists for the branch, reuse it — do not open a duplicate.
- Doc auto-fixes are limited to deterministic values (coverage percentage, dates) and factual corrections (wrong command name, renamed module). Editorial-judgment changes must be flagged to the user.
- Out-of-scope triage (step 9) is mandatory — never skip it silently.
- Known-issues entries are always a separate follow-up commit (step 13).
- If any `gh` or `git push` command fails, report verbatim and stop. No silent retries.

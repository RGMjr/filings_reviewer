# Contributing

## One-time setup

```bash
# Install dependencies (uv-managed virtualenv).
make install

# Install git hooks (ruff on commit, unit tests on push).
make hooks-install
```

If `make hooks-install` reports that `core.hooksPath` was previously set to a
now-deleted `.githooks/` directory, clear it once:

```bash
git config --unset core.hooksPath
```

Environment setup (`DATABASE_URL`, `SEC_USER_AGENT`, `FILINGS_API_KEY`) is
covered in [`docs/operations/setup-guide.md`](../operations/setup-guide.md).

## Workflow

```
feature branch → PR against main → CI green → squash-merge
```

`main` is protected (see
[`docs/operations/ci-branch-protection.md`](../operations/ci-branch-protection.md)).
Direct pushes are refused; a red CI blocks the merge button. Branches do NOT need to be up-to-date with `main` before merging — auto-merge squash-merges whichever PR finishes CI first; subsequent PRs merge on top.

Run `/commit` from a `ccw` worktree. HEAD-moving git commands in the primary tree are blocked by a PreToolUse hook — see `docs/development/claude-sessions-and-worktrees.md`.

### Committing via `/commit` (Claude Code)

The project-local `/commit` skill (`.claude/commands/commit.md`) handles the
full flow in one invocation:

1. **Branch preflight.** If on `main`, auto-creates `claude/<type>-<slug>` and
   switches to it. Otherwise stays on the current branch.
2. **Pre-commit framework check.** Verifies `.git/hooks/pre-commit` is
   installed; if missing, runs `make hooks-install`.
3. **Lint + tests + doc-freshness + known-issues triage** (unchanged).
4. **Commit** (primary) + optional `docs(known-issues): ...` follow-up commit.
5. **Push** the branch: `git push -u origin <branch>`.
6. **PR.** If no open PR exists for the branch: `gh pr create --fill`. If
   one already exists: reuse it (new commits are appended).
7. **Auto-merge.** `gh pr merge --auto --squash`. GitHub merges the PR once
   all required checks pass (Lint / Unit Tests / Vulnerability Scan /
   Integration Tests / UI E2E).

Local safety rails in `.claude/settings.json`:

- `git push origin main`, `git push --force*`, and `gh pr merge*--admin*` are
  denied before the Bash tool fires them.
- A PreToolUse hook refuses `git commit` while on `main` (belt-and-suspenders
  if you bypass `/commit`).

### When checks fail

- **Red CI on a PR:** invoke `/ci-fix` — it iterates ruff/mypy/pytest to
  green, then defers to `/commit` to push the fix. Auto-merge stays armed and
  completes when the next run is green.
- **Pre-merge sanity:** `/merge-check` runs the full local gauntlet (CI
  status, migrations, import integrity, tests, type check, branch freshness)
  and reports blockers without taking any action.
- **Disable auto-merge on a specific PR:** `gh pr merge --disable-auto <num>`.

### Escape hatches

- `git push --no-verify` skips only the **pre-push** unit-test hook. CI still
  runs the full suite and must pass for the merge button to enable.
- The PreToolUse hook's `BLOCKED: refusing to commit on main` message is
  recoverable: `git checkout -b <branch>` and retry the commit.
- Do **not** use `gh pr merge --admin` — it's denied in settings and bypasses
  required status checks. `enforce_admins: true` on the branch protection
  rule would reject it server-side anyway.

## What runs on commit

`.pre-commit-config.yaml` runs on every `git commit`:

- `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-added-large-files`, `detect-private-key`
- `ruff --fix` (auto-fixes simple lint)
- `ruff-format` (formatter)

Runtime: under 2 seconds. If ruff auto-fixes anything, the commit will fail
once — re-stage (`git add -u`) and commit again.

## What runs on push

`pytest tests/unit/ -x -q --no-cov` runs before the push hits the network.

- Runtime: ~25 seconds.
- Catches unit-test regressions before they surface as a red PR.

### Escape hatch

If you've just run tests manually and know they pass, skip the pre-push hook:

```bash
git push --no-verify
```

CI still runs the full suite on the server — `--no-verify` does **not** bypass
CI, only the local pre-push check. Use it when you're iterating rapidly and
confident; don't use it to paper over a failing test.

## What CI gates before merge

The [branch-protection runbook](../operations/ci-branch-protection.md) lists
the required jobs. At time of writing:

| Gate | What it enforces |
|---|---|
| `Lint` | `ruff check src/ tests/ scripts/` clean |
| `Unit Tests` | 3000+ tests pass, coverage ≥80% |
| `Vulnerability Scan` | `pip-audit` reports no known CVEs |
| `Integration Tests` | Real Postgres exercise; SQL + migration regressions |
| `UI E2E (Playwright)` | Review-UI template / route rendering |

Coverage threshold (`fail_under`) and the suite's expectations are in
`pyproject.toml` under `[tool.coverage.report]` and `[tool.pytest.ini_options]`.

## Commit style

Conventional-commits format, checked loosely by reviewer eyeball (not
mechanically enforced):

```
type(scope): short subject line <=72 chars

Body explaining the why, not the what.

Co-Authored-By: ...
```

Types used in this repo: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`.

## Staging files

Never use `git add -A` or `git add .` — the repo has a history of parallel
Claude sessions leaving unrelated changes in the working tree. Always stage
specific files by name.

## Known-issues triage

New issues surfaced during contribution go into `docs/KNOWN_ISSUES.md` with
the next available number. See the existing entries for the expected shape
(Status / Severity / Problem / Resolution or Next Steps).

`docs/KNOWN_ISSUES.md` is auto-generated from fragment files under
`docs/known-issues/`.  Edit the per-issue fragment, not the rollup directly.
A pre-commit hook regenerates and re-stages the rollup automatically whenever
you stage a fragment.

### Merge conflicts on `docs/KNOWN_ISSUES.md`

`docs/KNOWN_ISSUES.md` is auto-generated from `docs/known-issues/*.md`. When
you hit a merge conflict on the rollup, don't resolve the conflict markers
by hand — the file is fully deterministic given the fragment set, so:

1. `git merge --abort` if the merge isn't otherwise useful, or just accept
   either side for this file.
2. `rm docs/KNOWN_ISSUES.md`
3. `python3 scripts/regenerate_known_issues.py`
4. `git add docs/KNOWN_ISSUES.md && git commit`

If the conflict is *also* on `docs/known-issues/legacy-NNN-*.md` fragment
files, resolve those conflicts normally first (they carry the real
information) — then regenerate the rollup as above.

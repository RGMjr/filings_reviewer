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
Direct pushes are refused; a red CI blocks the merge button.

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
| `Unit Tests` | 3000+ tests pass, coverage ≥75% |
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

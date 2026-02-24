# WI-02: GitHub Actions CI Pipeline

**Branch**: `prod/wi-02-ci-pipeline`
**Depends on**: Nothing (independent)
**Blocks**: Nothing (but all other WIs benefit from it)
**Risk level**: Low (no application code changes)
**Execution**: `/ralph develop --isolated`

---

## Context

No GitHub Actions workflow exists for the `v2-rewrite` branch. There is no automated check that runs when code is pushed or a PR is opened. This means:

- Regressions in extraction quality go undetected until manual validation
- Test failures on WIP changes are discovered by hand
- The gold standard score is only validated when someone remembers to run it

This work item creates a CI workflow that covers linting, unit tests, integration tests (with a Postgres service container), and gold standard validation.

---

## Implementation

### File to Create

Create `.github/workflows/v2-ci.yml`.

### Workflow Design

```yaml
name: V2 CI

on:
  push:
    branches: [v2-rewrite]
  pull_request:
    branches: [main]
    paths:
      - 'src/**'
      - 'tests/**'
      - 'sql/**'
      - 'scripts/**'
      - 'config/**'
      - '.github/workflows/v2-ci.yml'

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run ruff check src/ tests/ scripts/

  unit-tests:
    name: Unit Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - run: uv run pytest tests/unit/ -x -q --tb=short
      - run: uv run pytest tests/unit/ --co -q | tail -1  # Print test count

  integration-tests:
    name: Integration Tests
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: filings_analysis_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/filings_analysis_test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - name: Apply migrations
        run: uv run python3 scripts/apply_migrations.py --test
      - name: Run integration tests
        run: uv run pytest tests/integration/ -x -q --tb=short

  gold-standard:
    name: Gold Standard
    runs-on: ubuntu-latest
    needs: [unit-tests]
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: filings_analysis_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/filings_analysis_test
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true  # Gold standard HTML fixtures may be in LFS
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --dev
      - name: Apply migrations
        run: uv run python3 scripts/apply_migrations.py --test
      - name: Run gold standard validation
        run: |
          uv run pytest -m gold_standard --gold-standard-mode=fresh -v \
            --tb=short 2>&1 | tee gold-standard-output.txt
      - name: Upload gold standard results
        uses: actions/upload-artifact@v4
        with:
          name: gold-standard-results
          path: gold-standard-output.txt
          retention-days: 30
```

### Key Design Decisions

**Why 4 jobs instead of 1?**
- Lint and unit tests are fast (<2 min) and catch most issues. They should not wait for Postgres to spin up.
- Integration tests and gold standard need Postgres. They run in parallel after lint passes.
- Gold standard is gated on unit tests (`needs: [unit-tests]`) to avoid wasting Postgres time when code is obviously broken.

**Why Postgres 16 instead of the project's Docker Compose version?**
- The project uses port 5433 via Docker Compose (non-standard). GitHub Actions service containers always use 5432. The `TEST_DATABASE_URL` env var points to 5432 in CI.
- This is fine: the app code uses whatever URL is in `TEST_DATABASE_URL`.

**Why not pin the gold standard F1 as a hard failure threshold?**
- The gold standard test suite (`-m gold_standard --gold-standard-mode=fresh`) already compares against `data/gold_standard/v2_baseline.json` and fails if any metric regresses beyond the 1% tolerance.
- The artifact stores the full output for manual review when there are regressions.
- Adding a separate threshold check would duplicate logic already in the test suite.

**Gold standard data fixtures**
- The HTML filing fixtures used by gold standard tests must be accessible in CI.
- Check `tests/conftest.py` and `pytest -m gold_standard` config to confirm where fixtures live.
- If fixtures are large (>100MB), configure Git LFS or download them as part of the CI step.
- If fixtures are committed directly, ensure they are in the repo and the `lfs: true` flag is not needed.

---

## Files to Create

| File | Description |
|------|-------------|
| `.github/workflows/v2-ci.yml` | The workflow file |

---

## Acceptance Criteria

- [ ] Workflow triggers on push to `v2-rewrite` and on PRs targeting `main`
- [ ] Lint job runs `ruff check` and fails on lint errors
- [ ] Unit tests job runs all tests under `tests/unit/` and fails on any test failure
- [ ] Integration tests job runs with a live Postgres 16 container; migrations applied via `apply_migrations.py --test`
- [ ] Gold standard job uploads results as a workflow artifact
- [ ] All 4 jobs pass on the current `v2-rewrite` branch

---

## Verification Commands

```bash
# Verify workflow syntax locally (requires act or GitHub CLI)
gh workflow view v2-ci.yml

# After pushing the workflow file, check it runs
gh run list --workflow=v2-ci.yml

# Check a specific run
gh run view <run-id>
```

---

## Pre-flight Checks

Before creating the workflow, verify:

1. Does `.github/workflows/` directory exist? If not, create it.
2. Does the repo have access to GitHub Actions? (`gh repo view --json hasWiki` — check billing/settings)
3. Are gold standard HTML fixtures in the repo or on an external store?
   ```bash
   du -sh tests/data/gold_standard/  # or wherever fixtures live
   ```
4. Does `uv` work in the project root? (Check `pyproject.toml` for `[tool.uv]` section)
5. What is the actual Postgres port used in `docker-compose.yml`? (5433 or 5432)

Address any gaps found during Recon before writing the workflow file.

# Repository Guidelines

## Project Structure & Module Organization
Source lives under `src/` with domain modules grouped by function: `universe/` (UniverseBuilder logic and classifiers), `infra/` (database + SEC clients), `filing_fetcher/` and `extraction/` stubs for downstream stages. Tests mirror this under `tests/unit` and `tests/integration`; add fixtures to `tests/data` if needed. SQL migrations are in `sql/` (start with `01_create_schema.sql`). Specs and research notes are in `docs/`, while operational scripts land in `scripts/`. Keep cached data or logs inside `data/` or `Archive/` to avoid polluting Git history.

## Build, Test, and Development Commands
```bash
pip install -r requirements.txt        # install deps
python -m src.universe.universe_builder # run module directly for smoke tests
python examples/build_universe_example.py --mode mock
pytest                                 # unit + coverage (htmlcov/)
ruff check . && black .                 # lint + format
```
Use `.env` (see README) to point `DATABASE_URL` or `TEST_DATABASE_URL` at a disposable Postgres instance before running real SEC pulls.

## Coding Style & Naming Conventions
Use Python 3.11 features (type hints, dataclasses). Keep modules small and prefer functional helpers in `src/universe/classifiers.py`. Follow Black’s defaults (88 chars, double quotes) and run Ruff before committing; fix warnings rather than silencing them. Name async tasks, SQL files, and scripts with snake_case, e.g., `scripts/setup_test_db.py`. When adding markers, register them in `pytest.ini`.

## Testing Guidelines
Pytest is configured in `pytest.ini` with strict markers and coverage gates (`--cov=src`). Keep unit tests fast and deterministic; long-running or DB-backed scenarios belong under `tests/integration` and should use the `integration` marker plus `TEST_DATABASE_URL`. Name tests `test_<feature>_<condition>` to document behavior. Generate coverage locally (`htmlcov/index.html`) before opening a PR and include regression fixtures when classifiers change.

## Commit & Pull Request Guidelines
Commits are squashed regularly, so keep messages imperative and scoped (“Add SPAC keyword audit”). Reference Jira/GitHub issues in the body if applicable. PRs must summarize scope, note schema/ETL impacts, and confirm `pytest`, `ruff`, and `black` output. Attach screenshots or log excerpts when you change extraction rules, and mention any manual data cleanup steps in the PR checklist.

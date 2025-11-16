# Repository Guidelines

## Project Structure & Module Organization
- `data_preprocessing.py` is the current orchestration script; it fetches S-1/S-1A indexes, enriches filings with metadata, and performs keyword-driven extraction. Keep experimental steps in separate functions within this file or migrate them into future `core/` modules before merging.
- `docs/` hosts numbered design references (e.g., `01_ARCHITECTURE_OVERVIEW.md`, `07_TESTING_STRATEGY.md`). Cite these documents in PRs when you change the described behavior.
- Output artifacts such as `s1_fetch_records.csv`, `s1_keyword_paragraphs.csv`, and cached HTML should live under `data/` (gitignored). Treat `__pycache__/` and `.pytest_cache/` as disposable.

## Build, Test, and Development Commands
- `python data_preprocessing.py`: end-to-end pipeline that downloads filings, extracts keywords, and writes CSVs.
- `python -m pytest`: run unit tests (add modules in `tests/` named `test_*.py`). Use `PYTEST_ADDOPTS="-k table_extractor"` for focused runs.
- `ruff check .` and `black .`: lint and auto-format; run both before pushing to avoid CI failures.
- `mypy data_preprocessing.py`: spot type regressions once modules are extracted.

## Coding Style & Naming Conventions
- Python 3.11+, 4-space indentation, and `snake_case` for functions/variables (`fetch_quarter`, `keyword_hits`).
- Constants in `UPPER_SNAKE` (`HEADERS`, `FORMS`); keep HTTP headers near fetch helpers so reviewers can verify compliance with SEC rules.
- Prefer pure functions that accept explicit parameters; avoid hidden global state besides configuration constants.
- Format code with Black’s defaults (88-char line cap) and keep imports grouped: stdlib, third-party, local.

## Testing Guidelines
- Follow `docs/07_TESTING_STRATEGY.md` for the pyramid: start with unit tests that mock SEC/LLM calls, then graduate to integration pilots.
- Place tests inside `tests/` mirroring the module path (`tests/test_table_extractor.py` for `core/table_extractor.py`).
- Name fixtures descriptively (`mock_openai_response`) and seed deterministic sample HTML snippets so reviewers can reason about expectations.
- Before large refactors, run `python -m pytest` plus representative smoke runs of `python data_preprocessing.py --max-results 3` to confirm EDGAR compatibility.

## Commit & Pull Request Guidelines
- Commits follow short, imperative summaries (see `git log`: “Rethink process flow”, “Add environment configuration test script”). Keep scope tight and avoid stacking unrelated fixes.
- PRs should include: purpose, affected docs/modules, run commands (`pytest`, `ruff`, pipeline smoke), data-impact notes, and any screenshots of CSV diffs or console output when relevant.

## Security & Configuration Tips
- Store secrets only in `.env` (`OPENAI_API_KEY`, `DATABASE_PATH`, cache paths) and never echo them in logs or commits.
- Respect SEC rate limits: throttle requests (`time.sleep(0.25)`) and keep the `HEADERS` contact email accurate before running large batches.
- Treat generated CSVs as confidential; scrub PII before sharing outside the repo.

---
paths:
  - "tests/**"
---

# Testing Rules

## Standards

- **Coverage**: 80% minimum (enforced)
- **Type safety**: `src/review/` passes `mypy --strict`

## Structure

- `tests/unit/` - Fast, isolated unit tests (no external dependencies)
- `tests/integration/` - Requires `TEST_DATABASE_URL` environment variable. Under `pytest-xdist` (`-n auto`), each worker gets its own Postgres DB (`<base>_gw0`, `_gw1`, …) via `tests/integration/conftest.py::_isolate_xdist_worker_database` — the configured role must have `CREATEDB`. Sequential mode is a no-op.

## Commands

```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/unit/test_module.py -v

# Run tests matching pattern
pytest -k "test_pattern" -v
```

## Gold Standard Tests

When modifying extraction or keyword logic, run:
```bash
python3 -m src.gold_standard.v2_validator
```

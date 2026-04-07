---
paths:
  - "tests/**"
---

# Testing Rules

## Standards

- **Coverage**: 75% minimum (enforced)
- **Type safety**: `src/review/` passes `mypy --strict`

## Structure

- `tests/unit/` - Fast, isolated unit tests (no external dependencies)
- `tests/integration/` - Requires `TEST_DATABASE_URL` environment variable

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
pytest -m gold_standard --gold-standard-mode=fresh -v
```

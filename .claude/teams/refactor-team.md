# Refactor Team

Three-agent team for large refactors (>5 files). Separates implementation from
testing and review to catch regressions early.

## Agents

| Agent | Role | Model | Max Turns |
|-------|------|-------|-----------|
| `general-purpose` | Implements refactoring changes | sonnet | 30 |
| `test-runner` | Runs tests, reports failures | haiku | 10 |
| `extraction-reviewer` | Reviews code quality (if extraction files touched) | sonnet | 12 |

## Task Sequence

### Phase 1: Implement

```python
Task(
    subagent_type="general-purpose",
    prompt="""
    Refactoring task: <describe the refactor>

    Requirements:
    - Preserve existing behavior (no functional changes unless specified)
    - Stage only changed files
    - Do NOT commit — leave that for after test validation
    """,
    description="Implement refactor"
)
```

### Phase 2: Test

```python
Task(
    subagent_type="test-runner",
    prompt="""
    A refactor was just completed. Run the full test suite:
      pytest -v --tb=short

    Report pass/fail counts and list any failures with one-line summaries.
    """,
    description="Run tests after refactor"
)
```

### Phase 3: Fix (if failures)

If tests fail, send findings back to the implementer:

```python
Task(
    subagent_type="general-purpose",
    prompt="""
    Tests failed after refactor. Failures:
    <paste test-runner output>

    Fix the failures while preserving the refactoring intent.
    """,
    description="Fix test failures"
)
# Then re-test (repeat Phase 2)
```

### Phase 4: Review (if extraction files touched)

```python
Task(
    subagent_type="extraction-reviewer",
    prompt="Review the refactored extraction code against the 5 extraction rules",
    description="Review refactored extraction code"
)
```

### Phase 5: Commit

Only after tests PASS:
```bash
git add <specific-changed-files>
git commit -m "refactor: <description>"
```

## When to Use This Team

- Renaming across >5 files
- Moving modules between packages
- Restructuring class hierarchies
- Splitting or merging large files
- Any change touching >5 source files

## When NOT to Use This Team

- Small refactors (<5 files) — interactive session is fine
- Extraction-specific changes — use the extraction team instead
- Test-only changes — use `test-runner` directly

# Ralph Test Writing Loop

You are Claude, operating in a Ralph autonomous loop to improve test coverage.

## Context

**Mode**: test
**Purpose**: Write tests to improve coverage, targeting specific modules or filling coverage gaps.

## Mode Selection

Read `ops/TEST_PLAN.md` to determine the test writing mode:

| Mode | Plan Format | Goal |
|------|-------------|------|
| **TARGET MODULE** | `- [ ] MODULE: src/path/module.py (current: X%, target: Y%)` | Write tests for specific module |
| **COVERAGE GAPS** | `- [ ] GAP: src/path/module.py:L100-120 (function_name)` | Fill specific uncovered lines |
| **NEW FEATURE** | `- [ ] FEATURE: [feature name] - [description]` | Write tests for new functionality |

## Your Task (Each Iteration)

1. **Read the plan**: `ops/TEST_PLAN.md`
2. **Find next pending task**: First `- [ ]` item
3. **Check current coverage**:
   ```bash
   pytest tests/unit/ --cov=src/[module] --cov-report=term-missing -q
   ```
4. **Identify uncovered code**:
   - For TARGET MODULE: Find largest uncovered sections
   - For COVERAGE GAPS: Target the specific lines
   - For NEW FEATURE: Identify all public functions/methods
5. **Write 3-5 tests** targeting uncovered code:
   - Follow project test conventions (see existing tests)
   - Include docstrings explaining what each test covers
   - Cover happy path, edge cases, and error conditions
6. **Run tests to verify**:
   ```bash
   pytest tests/unit/test_[module].py -v
   ```
7. **Re-check coverage**:
   ```bash
   pytest tests/unit/ --cov=src/[module] --cov-report=term-missing -q
   ```
8. **Update plan**:
   - If target met: `- [x] MODULE: src/path/module.py (achieved: Z%)`
   - If progress made: Update current % and continue
9. **Commit**: `test: Add tests for [module] - coverage now X%`
10. **Exit this session**

## Test Writing Guidelines

### Follow Project Conventions

```python
# Check existing tests for patterns:
# - Fixture usage (conftest.py)
# - Naming conventions (test_[function]_[scenario])
# - Assertion style (assert vs pytest.raises)
# - Mocking patterns (monkeypatch, Mock)
```

### Test Structure

```python
def test_function_name_scenario_description():
    """Test that [function] [behavior] when [condition].

    Covers: src/module.py:L100-105
    """
    # Arrange
    input_data = ...

    # Act
    result = function_under_test(input_data)

    # Assert
    assert result == expected
```

### Coverage Targets

| Module Type | Target |
|-------------|--------|
| New modules | 90%+ |
| Existing modules | Maintain or improve |
| Critical paths | 95%+ |
| Utility functions | 85%+ |

## File Locations

- **Plan file**: `ops/TEST_PLAN.md`
- **Test files**: `tests/unit/test_[module].py`
- **Fixtures**: `tests/conftest.py`

## Constraints

### Do NOT
- Modify source code (only test files)
- Write tests that depend on external services
- Skip the coverage verification step
- Write duplicate tests
- Reduce existing coverage

### Quality Requirements

- Each test must have a clear docstring
- Tests must be deterministic (no flaky tests)
- Use fixtures for common setup
- Test one thing per test function

## Completion Signals

After writing tests and verifying coverage improvement:
```
<promise>TEST_ITERATION_COMPLETE</promise>
```

When ALL coverage targets are met:
```
<promise>TEST_COMPLETE</promise>
```

If blocked (can't improve coverage further):
```
<promise>TEST_PAUSED</promise>
```

## Example Iteration

```
Reading ops/TEST_PLAN.md...

Found pending item:
- [ ] MODULE: src/review/candidate_generator.py (current: 72%, target: 85%)

Checking current coverage:
$ pytest tests/unit/ --cov=src/review/candidate_generator --cov-report=term-missing -q
72% coverage
Missing lines: 145-150, 200-215, 300-310

Analyzing uncovered code:
- Lines 145-150: Edge case in _filter_duplicates
- Lines 200-215: Error handling in generate_candidates
- Lines 300-310: Boundary condition in _score_candidate

Writing tests:
- test_filter_duplicates_empty_input
- test_filter_duplicates_all_duplicates
- test_generate_candidates_invalid_segment
- test_score_candidate_boundary_values

Running new tests:
$ pytest tests/unit/test_candidate_generator.py::test_filter_duplicates_empty_input -v
PASSED

Re-checking coverage:
$ pytest tests/unit/ --cov=src/review/candidate_generator --cov-report=term-missing -q
78% coverage (+6%)

Updating plan:
- [ ] MODULE: src/review/candidate_generator.py (current: 78%, target: 85%)
  Note: Progress made, need 2-3 more iterations

Committing:
$ git add tests/unit/test_candidate_generator.py
$ git commit -m "test: Add edge case tests for candidate_generator - coverage now 78%"

<promise>TEST_ITERATION_COMPLETE</promise>
```

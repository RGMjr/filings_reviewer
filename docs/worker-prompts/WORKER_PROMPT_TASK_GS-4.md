# WORKER PROMPT: Task GS-4 - pytest Integration Tests

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GS-4
TASK NAME:     Create pytest integration tests for gold standard regression
WORKSTREAM:    Testing Infrastructure
SOURCE:        Gold Standard Regression Testing Framework Plan
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (implementation 1.5 hr, testing 1 hr)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (new test file, no production code modified)
TASK SIZE:     M
DEPENDS ON:    GS-2
UNLOCKS:       GS-5
BLOCKS:        None
PARALLEL WITH: GS-3
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create pytest integration tests that validate metrics against the gold standard baseline and fail CI when regressions occur.

**Business Rationale**: Automated CI testing ensures that keyword or extraction logic changes don't silently regress metric quality. Developers get immediate feedback on pull requests.

**Current Behavior**: Gold standard validation requires manual script execution; no CI integration exists.

**Desired Behavior**: `pytest -m gold_standard` runs regression tests that fail if precision, recall, or F1 drops below baseline.

## Prerequisites

- GS-2 complete (validation script with baseline support)

## Files to Create

1. **`tests/integration/test_gold_standard_regression.py`** - pytest tests for regression detection

## Files to Modify

1. **`tests/conftest.py`** - Add pytest CLI options and fixtures for gold standard tests

## Files to Read (Context Only)

- `scripts/validate_against_gold_standard.py` - Validation logic to wrap
- `src/gold_standard/baseline.py` - Baseline loading/comparison
- `tests/integration/test_gold_standard_coverage.py` - Existing gold standard tests
- `pyproject.toml` - pytest configuration reference

## Implementation Requirements

### Core Functionality

1. **pytest Marker**
   - Add `@pytest.mark.gold_standard` marker for these tests
   - Tests should be skippable with `pytest -m "not gold_standard"`

2. **CLI Options (conftest.py)**
   - `--gold-standard-mode=fresh|db` - Extraction mode (default: db)
   - `--gold-standard-update-baseline` - Update baseline instead of comparing
   - `--gold-standard-tolerance=FLOAT` - Regression tolerance (default: 0.01)

3. **Test Classes**
   ```python
   @pytest.mark.gold_standard
   class TestGoldStandardRegression:
       def test_overall_precision_above_baseline(self):
           """Fail if precision drops below baseline threshold."""

       def test_overall_recall_above_baseline(self):
           """Fail if recall drops below baseline threshold."""

       def test_overall_f1_above_baseline(self):
           """Fail if F1 drops below baseline threshold."""

       def test_no_new_false_negatives_per_company(self):
           """Fail if any company's recall dropped significantly."""
   ```

4. **Fixtures**
   - `gold_standard_mode` - Returns mode from CLI or default
   - `baseline_metrics` - Loads baseline from file
   - `current_metrics` - Runs validation and returns current metrics
   - `comparison_result` - Compares current vs baseline

5. **Assertion Messages**
   - Include current and baseline values
   - Show delta and threshold
   - List affected companies if applicable

### Error Handling

- **Missing baseline**: Skip tests with informative message
- **Missing filings**: Skip individual company tests, don't fail suite
- **Validation errors**: Fail test with clear error message

## Test Requirements

### Coverage Target: **6+ test functions** exercising all regression detection paths

### Test Structure (6+ test functions)

1. **Overall Metrics** (3 tests)
   - Precision above baseline
   - Recall above baseline
   - F1 above baseline

2. **Per-Company Metrics** (2 tests)
   - No company recall regression
   - Aggregate company metrics check

3. **Edge Cases** (1-2 tests)
   - Behavior with missing baseline
   - Behavior with empty gold standard

### Example Test Implementation

```python
@pytest.mark.gold_standard
class TestGoldStandardRegression:
    def test_overall_precision_above_baseline(
        self, current_metrics, baseline_metrics, gold_standard_tolerance
    ):
        """Fail if precision drops below baseline threshold."""
        delta = current_metrics.overall.precision - baseline_metrics.overall.precision
        threshold = -gold_standard_tolerance

        assert delta >= threshold, (
            f"Precision regressed: {current_metrics.overall.precision:.1%} "
            f"(baseline: {baseline_metrics.overall.precision:.1%}, "
            f"delta: {delta:+.1%}, threshold: {threshold:+.1%})"
        )
```

## Acceptance Criteria

- [ ] `@pytest.mark.gold_standard` marker registered
- [ ] `--gold-standard-mode` CLI option works
- [ ] `--gold-standard-tolerance` CLI option works
- [ ] Test for precision regression
- [ ] Test for recall regression
- [ ] Test for F1 regression
- [ ] Test for per-company regressions
- [ ] Clear assertion messages with metrics
- [ ] Tests skipped gracefully if baseline missing
- [ ] `pytest -m gold_standard` runs only these tests
- [ ] `pytest -m "not gold_standard"` excludes these tests

## Do NOT

- Modify the validation script (use as-is from GS-2)
- Add tests that modify the baseline (update-baseline is CLI feature)
- Make tests that require database (use `--mode fresh` by default if possible)
- Create tests that take more than 60 seconds each

## Verification Commands

```bash
# Register marker
grep -q "gold_standard" pyproject.toml || grep -q "gold_standard" pytest.ini

# Run gold standard tests only
pytest -m gold_standard -v

# Run without gold standard tests
pytest -m "not gold_standard" tests/unit/ -v --co -q | head -20

# Check CLI options
pytest --help | grep gold-standard
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task GS-4: pytest Integration Tests
set -e

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "Verifying Task GS-4: pytest Integration Tests"
echo "═══════════════════════════════════════════════════════════════════════════════"

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check test file exists
echo "Checking: test_gold_standard_regression.py exists..."
test -f tests/integration/test_gold_standard_regression.py

# Check marker is registered
echo "Checking: gold_standard marker registered..."
pytest --markers 2>/dev/null | grep -q "gold_standard" || \
  grep -q "gold_standard" pyproject.toml || \
  grep -q "gold_standard" pytest.ini

# Check CLI options exist
echo "Checking: --gold-standard-mode option exists..."
pytest --help | grep -q "gold-standard-mode"

echo "Checking: --gold-standard-tolerance option exists..."
pytest --help | grep -q "gold-standard-tolerance"

# List gold_standard tests (collection only)
echo "Checking: gold_standard tests are discoverable..."
pytest -m gold_standard --co -q tests/integration/test_gold_standard_regression.py

# Run the tests (with db mode to avoid slow fresh extraction)
echo "Running gold_standard tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  pytest -m gold_standard tests/integration/test_gold_standard_regression.py -v

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "All acceptance criteria verified for Task GS-4!"
echo "═══════════════════════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size (M = thorough review).**

After verification passes but BEFORE committing:
1. Code Quality Review (linting, DRY, naming, error handling)
2. Test Coverage Assessment (edge cases, negative tests)
3. Architecture Alignment (CLAUDE.md patterns, minimal changes)
4. Identify Improvements (optimizations, edge cases, simplifications)
5. **User Approval (REQUIRED)** - STOP and ask user before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for deferred improvements
8. Update Documentation
9. Commit and Push

## Reference

- **Issue source**: Gold Standard Regression Testing Framework Plan
- **Dependencies**: GS-2 (validation script with baseline)
- **Related**: tests/integration/test_gold_standard_coverage.py (existing tests)

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4

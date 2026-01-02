# WORKER PROMPT: Task GS-1 - Baseline Metrics Infrastructure

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GS-1
TASK NAME:     Create baseline metrics infrastructure for gold standard validation
WORKSTREAM:    Testing Infrastructure
SOURCE:        Gold Standard Regression Testing Framework Plan
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-1.5 hours (implementation 45 min, tests 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (new isolated module, no existing code modified)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       GS-2
BLOCKS:        GS-2
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create a baseline metrics module that stores and retrieves precision/recall/F1 metrics for comparing gold standard validation runs over time.

**Business Rationale**: When keyword patterns or extraction logic changes, we need to know if metrics improved or regressed. A baseline file provides the reference point for comparison.

**Current Behavior**: The validation script calculates metrics but has no way to compare against historical baselines or detect regressions.

**Desired Behavior**: Metrics can be saved to a JSON baseline file and loaded for comparison, with clear delta reporting.

## Prerequisites

- None (standalone task)

## Files to Create

1. **`src/gold_standard/__init__.py`** - Package init (can be empty)
2. **`src/gold_standard/baseline.py`** - Baseline metrics management module
3. **`tests/unit/gold_standard/__init__.py`** - Test package init (can be empty)
4. **`tests/unit/gold_standard/test_baseline.py`** - Unit tests for baseline module

## Files to Read (Context Only)

- `scripts/validate_against_gold_standard.py` - Existing validation script to understand metric structures
- `data/gold_standard/golden_set_251218.csv` - Gold standard format reference

## Implementation Requirements

### Core Functionality

1. **BaselineMetrics Data Class**
   - Store overall precision, recall, F1 scores
   - Store per-company breakdown with same metrics
   - Store baseline creation date and description
   - Support JSON serialization/deserialization

2. **Save Baseline** (`save_baseline(metrics, path)`)
   - Write BaselineMetrics to JSON file
   - Include timestamp and description
   - Create parent directories if needed

3. **Load Baseline** (`load_baseline(path)`)
   - Read JSON file into BaselineMetrics object
   - Raise FileNotFoundError if baseline doesn't exist
   - Validate JSON structure on load

4. **Compare Metrics** (`compare_to_baseline(current, baseline)`)
   - Calculate delta for precision, recall, F1
   - Return structured comparison result
   - Flag regressions (negative delta beyond tolerance)

5. **Data Structure**
   ```python
   @dataclass
   class MetricScores:
       precision: float  # 0.0-1.0
       recall: float     # 0.0-1.0
       f1: float         # 0.0-1.0

   @dataclass
   class BaselineMetrics:
       baseline_date: str          # ISO format
       description: str | None
       overall: MetricScores
       by_company: dict[str, MetricScores]

   @dataclass
   class ComparisonResult:
       precision_delta: float      # Positive = improvement
       recall_delta: float
       f1_delta: float
       has_regression: bool        # True if any metric dropped
       regressed_companies: list[str]
   ```

### Error Handling

- **Missing baseline file**: Raise `FileNotFoundError` with helpful message
- **Invalid JSON**: Raise `ValueError` with description of what's wrong
- **Missing fields**: Use defaults for optional fields, raise for required

## Test Requirements

### Coverage Target: **>= 90%** for `src/gold_standard/baseline.py`

### Test Categories (12+ tests recommended)

1. **Serialization** (3-4 tests)
   - Round-trip save/load preserves data
   - JSON format is human-readable
   - Handles special characters in company names

2. **Comparison** (4-5 tests)
   - Improvement detected (positive delta)
   - Regression detected (negative delta)
   - No change (zero delta)
   - Tolerance threshold respected

3. **Error Handling** (3-4 tests)
   - Missing file raises FileNotFoundError
   - Invalid JSON raises ValueError
   - Missing required fields raises error

### Known Edge Cases to Test

- Company name with commas or quotes
- Perfect scores (precision=1.0)
- Zero scores (precision=0.0)
- Very small deltas (0.001)

## Acceptance Criteria

- [ ] `BaselineMetrics` dataclass with JSON serialization
- [ ] `save_baseline()` function writes JSON
- [ ] `load_baseline()` function reads JSON
- [ ] `compare_to_baseline()` function returns ComparisonResult
- [ ] Regression detection with configurable tolerance
- [ ] **12+ unit tests** covering all categories
- [ ] **Test coverage >= 90%**
- [ ] All tests pass
- [ ] `mypy src/gold_standard/baseline.py --strict` passes

## Do NOT

- Modify `scripts/validate_against_gold_standard.py` (that's GS-2)
- Add database dependencies (file-based only)
- Create the actual baseline file (that happens when running with `--update-baseline`)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_baseline.py -v

# Check coverage (must be >= 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_baseline.py \
  --cov=src/gold_standard/baseline --cov-report=term-missing --cov-fail-under=90

# Type safety check
mypy src/gold_standard/baseline.py --strict
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task GS-1: Baseline Metrics Infrastructure
set -e

echo "==============================================================================="
echo "Verifying Task GS-1: Baseline Metrics Infrastructure"
echo "==============================================================================="

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check file exists
echo "Checking: baseline.py exists..."
test -f src/gold_standard/baseline.py

# Check test file exists
echo "Checking: test_baseline.py exists..."
test -f tests/unit/gold_standard/test_baseline.py

# Type safety
echo "Checking: mypy passes..."
mypy src/gold_standard/baseline.py --strict

# Tests + Coverage
echo "Checking: Tests pass with >= 90% coverage..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_baseline.py \
  --cov=src/gold_standard/baseline --cov-report=term-missing --cov-fail-under=90 -v

echo "==============================================================================="
echo "All acceptance criteria verified for Task GS-1!"
echo "==============================================================================="
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size (S = standard review).**

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
- **Dependencies**: None
- **Related**: GS-2 (integration with validation script)

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4

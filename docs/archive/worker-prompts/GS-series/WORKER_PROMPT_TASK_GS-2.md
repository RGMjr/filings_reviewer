# WORKER PROMPT: Task GS-2 - Enhanced Validation Script

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GS-2
TASK NAME:     Enhance validation script with baseline comparison and regression detection
WORKSTREAM:    Testing Infrastructure
SOURCE:        Gold Standard Regression Testing Framework Plan
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (implementation 1.5 hr, testing 1 hr)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (modifying existing script with new features)
TASK SIZE:     M
DEPENDS ON:    GS-1
UNLOCKS:       GS-3, GS-4, GS-5
BLOCKS:        GS-3, GS-4, GS-5
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Enhance the existing `validate_against_gold_standard.py` script to support baseline comparison, regression detection, and configurable thresholds.

**Business Rationale**: Developers need a single command to validate changes against the gold standard and know immediately if metrics regressed.

**Current Behavior**: Script calculates precision/recall/F1 but cannot compare against baselines or fail on regression.

**Desired Behavior**: Script supports `--baseline`, `--update-baseline`, `--fail-on-regression`, and exits non-zero when metrics regress.

## Prerequisites

- GS-1 complete (baseline module exists)

## Files to Modify

1. **`scripts/validate_against_gold_standard.py`** - Add baseline comparison features

## Files to Read (Context Only)

- `src/gold_standard/baseline.py` - Baseline module from GS-1
- `data/gold_standard/golden_set_251218.csv` - Gold standard data

## Implementation Requirements

### Core Functionality

1. **New CLI Arguments**
   - `--baseline` - Compare results against stored baseline, show delta
   - `--update-baseline` - Save current metrics as new baseline
   - `--fail-on-regression` - Exit with code 1 if any metric regressed
   - `--tolerance FLOAT` - Allowable regression tolerance (default 0.01 = 1%)
   - `--baseline-path PATH` - Path to baseline file (default: `data/gold_standard/baseline_metrics.json`)

2. **Baseline Comparison Output**
   - Show current vs baseline metrics side-by-side
   - Display delta with +/- indicators
   - Highlight regressions in output
   - Example:
     ```
     Metric Comparison (vs baseline 2025-12-15):
                    Current   Baseline   Delta
     Precision:      78.5%     75.2%    +3.3%
     Recall:         82.1%     84.0%    -1.9% [REGRESSION]
     F1 Score:       80.3%     79.4%    +0.9%
     ```

3. **Regression Detection**
   - Check if any metric dropped beyond tolerance
   - Report which metrics regressed
   - Report which companies regressed
   - Exit with code 1 if `--fail-on-regression` and regression detected

4. **Update Baseline Flow**
   - Calculate current metrics
   - Save to baseline file with current date
   - Print confirmation message

### Error Handling

- **Missing baseline with --baseline**: Print warning, continue without comparison
- **Invalid baseline file**: Print error, exit with code 2
- **No gold standard entries**: Print warning, skip validation

## Files to Create

1. **`tests/unit/gold_standard/test_validate_script.py`** - Unit tests for new CLI features

## Test Requirements

### Coverage Target: **>= 80%** for new baseline comparison code in script

### Test Categories (8+ tests recommended)

1. **CLI Arguments** (3-4 tests)
   - `--baseline` loads and compares correctly
   - `--update-baseline` saves file
   - `--fail-on-regression` exits non-zero on regression
   - `--tolerance` affects regression detection

2. **Output Format** (2-3 tests)
   - Delta display is correct (+/- signs)
   - Regression markers appear
   - Summary includes baseline date

3. **Edge Cases** (2-3 tests)
   - Missing baseline file with `--baseline`
   - Empty gold standard entries
   - First run (no baseline exists)

## Acceptance Criteria

- [ ] `--baseline` flag shows comparison to stored baseline
- [ ] `--update-baseline` flag saves current metrics
- [ ] `--fail-on-regression` exits 1 on regression
- [ ] `--tolerance` configures regression threshold
- [ ] Delta display shows +/- with color highlighting
- [ ] Regression warning clearly visible in output
- [ ] **8+ unit tests** covering CLI and comparison logic
- [ ] All existing tests still pass
- [ ] Script remains backward compatible (existing usage unchanged)

## Do NOT

- Change the core matching logic (precision/recall calculation)
- Modify database queries or connection handling
- Add fresh extraction mode (that's GS-3)
- Break existing `--filing-id`, `--company`, `--all` functionality

## Verification Commands

```bash
# Test existing functionality still works
python scripts/validate_against_gold_standard.py --help

# Test new baseline features (manual verification)
python scripts/validate_against_gold_standard.py --all --update-baseline
python scripts/validate_against_gold_standard.py --all --baseline
python scripts/validate_against_gold_standard.py --all --baseline --fail-on-regression

# Run tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_validate_script.py -v
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task GS-2: Enhanced Validation Script
set -e

echo "==============================================================================="
echo "Verifying Task GS-2: Enhanced Validation Script"
echo "==============================================================================="

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check help includes new arguments
echo "Checking: --baseline argument exists..."
python scripts/validate_against_gold_standard.py --help | grep -q "baseline"

echo "Checking: --update-baseline argument exists..."
python scripts/validate_against_gold_standard.py --help | grep -q "update-baseline"

echo "Checking: --fail-on-regression argument exists..."
python scripts/validate_against_gold_standard.py --help | grep -q "fail-on-regression"

echo "Checking: --tolerance argument exists..."
python scripts/validate_against_gold_standard.py --help | grep -q "tolerance"

# Run unit tests
echo "Running unit tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_validate_script.py -v

echo "==============================================================================="
echo "All acceptance criteria verified for Task GS-2!"
echo "==============================================================================="
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
- **Dependencies**: GS-1 (baseline module)
- **Related**: GS-3 (fresh extraction mode), GS-4 (pytest integration)

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4

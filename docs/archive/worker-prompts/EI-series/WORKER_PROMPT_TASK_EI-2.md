# WORKER PROMPT: Task EI-2 - Add Measurement Unit Patterns

```
===============================================================================
TASK ID:       EI-2
TASK NAME:     Add measurement unit patterns to false positive filter
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 - Issue #2
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-2_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 1-2 hours (implementation 30 min, testing 60-90 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Additive patterns to existing filter, no structural changes
PARALLEL WITH: EI-1, EI-3 (all independent Phase 1 tasks)
===============================================================================
```

## Objective

Filter out numbers that are part of measurement units (e.g., "24" in "24-hour period", "30" in "30-day window") to prevent them from being identified as metric values.

**Business Rationale**: Numbers in measurement units are part of metric definitions, not actual values. When a filing says "We define daily active users as users active in a 24-hour period", the "24" describes the measurement timeframe—not a customer metric quantity. These false positives waste reviewer time.

**Current Behavior**: Numbers in "24-hour period", "30-day window", "7-day average" patterns are not filtered. These numbers get extracted as candidate values.

**Desired Behavior**: Numbers immediately preceding time unit words (hour, day, week, month, year, etc.) are detected and filtered as false positives with reason "measurement_unit".

## Prerequisites

- None (standalone enhancement)
- Understand existing pattern structure in `FALSE_POSITIVE_CONTEXT_PATTERNS` (around line 157)
- Understand how patterns are checked against number positions in `is_false_positive()` method

## Files to Modify

1. **`src/review/false_positive_filter.py`** - Add measurement unit patterns to `FALSE_POSITIVE_CONTEXT_PATTERNS` (after line 182)

## Files to Read (Context Only)

- `src/review/false_positive_filter.py` - Understand existing pattern structure and `is_false_positive()` logic (lines 109-182 for patterns, lines 381-466 for filter method)
- `tests/unit/review/test_false_positive_filter.py` - Understand existing test patterns

## Implementation Requirements

### Core Functionality

1. **Measurement Unit Pattern Set**
   - Add regex patterns to detect numbers followed by time unit words
   - Support hyphenated format: "24-hour", "30-day", "7-week"
   - Support space-separated format: "24 hour", "30 day"
   - Support singular and plural: "day" and "days"
   - Cover common time units: hour, day, week, month, year, minute, second, period, quarter

2. **Pattern Location**
   - Add patterns to `FALSE_POSITIVE_CONTEXT_PATTERNS` list (after existing patterns around line 182)
   - Group patterns together with a comment header for maintainability

3. **Pattern Examples**
   ```python
   # Measurement unit patterns - numbers within time units are not metrics
   # Matches: "24-hour", "30-day", "7 days", "12-month", "90-second"
   re.compile(r"\b\d+[-\s]?(?:hour|day|week|month|year|period|quarter)s?\b", re.IGNORECASE),
   re.compile(r"\b\d+[-\s]?(?:minute|second)s?\b", re.IGNORECASE),
   ```

4. **Filter Reason**
   - The existing `is_false_positive()` returns "reference_number" for `FALSE_POSITIVE_CONTEXT_PATTERNS` matches
   - This is acceptable (no need to add a new reason category)
   - Alternatively, if better diagnostics desired, can add separate check with "measurement_unit" reason

### Error Handling

- **Pattern compilation**: Patterns must compile without errors (test at module load)
- **Case insensitivity**: Use `re.IGNORECASE` flag for all patterns
- **No exceptions**: Patterns use standard regex with no backtracking risk

### Performance Requirements

- Pattern matching is O(n) where n = context length (already in hot path)
- New patterns add ~2-4 regex matches per number (negligible overhead)
- No performance impact expected (<1ms additional per segment)

## Test Requirements

### Coverage Target: **Maintain ≥90%** for `src/review/false_positive_filter.py`

### Test Categories (8-10 tests recommended)

1. **Measurement Unit Detection - Hyphenated Format** (4 tests)
   - `test_24_hour_period_filtered` - "24-hour period" filters "24"
   - `test_30_day_window_filtered` - "30-day window" filters "30"
   - `test_12_month_period_filtered` - "12-month period" filters "12"
   - `test_7_week_average_filtered` - "7-week average" filters "7"

2. **Measurement Unit Detection - Space Format** (2 tests)
   - `test_24_hour_space_filtered` - "24 hour period" filters "24"
   - `test_30_day_space_filtered` - "30 day retention" filters "30"

3. **Measurement Unit Detection - Other Units** (2 tests)
   - `test_90_second_filtered` - "90-second timeout" filters "90"
   - `test_5_minute_filtered` - "5-minute interval" filters "5"

4. **Non-Measurement Numbers Pass Through** (2-3 tests)
   - `test_24000_customers_not_filtered` - "24,000 customers" NOT filtered
   - `test_numeric_value_not_filtered` - "grew 30% year over year" NOT filtered (30% not followed by unit)
   - `test_standalone_number_not_filtered` - "We have 12 million users" NOT filtered

### Test File Location

Add tests to: `tests/unit/review/test_false_positive_filter.py`

### Test Class/Function Names

```python
class TestMeasurementUnitPatterns:
    """EI-2: Measurement unit pattern filtering tests."""

    def test_24_hour_period_filtered(self):
        """24-hour period should filter out 24."""
        ...

    def test_30_day_window_filtered(self):
        """30-day window should filter out 30."""
        ...

    def test_space_separated_hour_filtered(self):
        """24 hour period (space) should filter out 24."""
        ...

    def test_plural_days_filtered(self):
        """30 days should filter out 30."""
        ...

    def test_legitimate_number_not_filtered(self):
        """24,000 customers should NOT be filtered."""
        ...
```

## Acceptance Criteria

- [ ] Numbers in "N-hour", "N-day", "N-week", "N-month", "N-year" patterns filtered
- [ ] Numbers in "N-minute", "N-second", "N-period", "N-quarter" patterns filtered
- [ ] Hyphenated format works: "24-hour"
- [ ] Space-separated format works: "24 hour"
- [ ] Singular and plural both work: "day" and "days"
- [ ] 8+ unit tests covering various time units
- [ ] All existing tests still pass (no regressions)
- [ ] NO impact on legitimate metric values (24,000 customers still passes)
- [ ] Coverage maintained ≥90% for `false_positive_filter.py`
- [ ] Type safety maintained (`mypy src/review/false_positive_filter.py --strict` passes)

## Do NOT

- Remove or modify existing patterns (additive change only)
- Change the `is_false_positive()` method logic (just add patterns)
- Add patterns for non-time units (scope is time units only for this task)
- Create new filter reason constants (use existing "reference_number" category)
- Modify other modules (changes contained to `false_positive_filter.py`)
- Change the `FalsePositiveFilter` class interface

## Verification Commands

```bash
# Run new tests specifically
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py::TestMeasurementUnitPatterns -v

# Verify no regressions in false positive filter tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py --no-cov -q

# Check coverage is maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py \
  --cov=src/review/false_positive_filter --cov-report=term-missing -q

# Type safety check
mypy src/review/false_positive_filter.py --strict

# Full review module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Expected Impact

**Before EI-2**:
- "24" from "24-hour period" extracted as candidate value
- "30" from "30-day retention window" extracted as candidate value
- Reviewers see false positives from metric definition language

**After EI-2**:
- Measurement unit numbers filtered out
- Only actual metric values pass through
- Estimated 3-5% reduction in false positive candidates

## Post-Implementation Tasks

After completing EI-2:

1. **Create Completion Summary**:
   - Create `docs/completion/EI-2_COMPLETION_SUMMARY.md` with:
     - Summary of patterns added
     - Test results and coverage
     - Any deviations from plan
     - Commit hash

2. **Update Documentation**:
   - Mark EI-2 as COMPLETE (✅) in `docs/EXTRACTION_IMPROVEMENT_PLAN.md` task table
   - Update status from 🟡 PENDING to ✅ COMPLETE with date

3. **Archive This Prompt**:
   - Move this file to `docs/archive/workstreams/EI-extraction-improvements/WORKER_PROMPT_TASK_EI-2.md`
   - Create the `EI-extraction-improvements` directory if it doesn't exist

4. **Commit and Push**:
   ```bash
   # Stage changes
   git add src/review/false_positive_filter.py \
           tests/unit/review/test_false_positive_filter.py \
           docs/EXTRACTION_IMPROVEMENT_PLAN.md \
           docs/completion/EI-2_COMPLETION_SUMMARY.md

   # Commit with descriptive message
   git commit -m "$(cat <<'EOF'
   EI-2: Add measurement unit patterns to false positive filter

   Add regex patterns to filter numbers that are part of time measurement
   units like "24-hour period", "30-day window", "7-week average". These
   numbers describe measurement timeframes, not actual metric values.

   Patterns added:
   - N-hour/N hour, N-day/N day, N-week/N week
   - N-month, N-year, N-quarter, N-period
   - N-minute, N-second
   - Singular and plural forms

   This reduces false positives from metric definition language where
   the measurement window is specified (e.g., "We define DAU as users
   active in a 24-hour period").

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"

   git push origin main
   ```

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Problem 1 (Definition segments) & Problem 4 (Definition as metrics)
- **Dependencies**: None (first task in Phase 1)
- **Related tasks**:
  - EI-1 (Definition Filtering) - can run in parallel
  - EI-3 (FalsePositiveFilter Integration) - can run in parallel, will use these patterns
  - EI-6 (Integration Testing) - depends on this task
- **Pattern location**: `FALSE_POSITIVE_CONTEXT_PATTERNS` list around line 157-182

---

**Last Updated**: 2025-12-18
**Format Version**: 2.2 (concise requirements-focused format)

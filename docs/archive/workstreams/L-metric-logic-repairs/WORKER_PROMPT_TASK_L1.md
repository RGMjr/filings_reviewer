# WORKER PROMPT: Task L1 - "Respectively" Pattern Parser

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       L1
TASK NAME:     Implement "respectively" pattern detection for parallel value-period associations
WORKSTREAM:    Metric Logic Repairs (L-series)
SOURCE:        MASTER_TASK_LIST.md, METRIC_IDENTIFICATION_ISSUES.md Issue 3
STATUS:        ✅ COMPLETE (2025-12-15)
COMPLETION:    docs/L1_COMPLETION_SUMMARY.md
TIME ESTIMATE: 2-3 hours
TIME ACTUAL:   2.5 hours
PARALLEL WITH: B13 (read-only), L2 (false_positive_filter.py), L3 (keyword_matching.py)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a standalone parser that detects "respectively" patterns and returns parallel associations between lists of values and lists of time periods.

**Business Rationale**: SEC filings use "respectively" to create parallel structures:
```
"Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
→ Should produce: [("33%", "2015"), ("35%", "2016"), ("43%", "2017")]
```

Currently the system creates three candidates but doesn't correctly associate values with their corresponding time periods.

## Prerequisites

- None (standalone module)
- Must NOT modify files being changed by L2/L3 (see constraints below)

## Files to Create

1. **`src/review/respectively_parser.py`** - Main parser module
2. **`tests/unit/review/test_respectively_parser.py`** - Comprehensive test suite

## Files to Read (Context Only)

- `src/review/models.py` - Understand existing data structures
- `src/review/number_parsing.py` - May reuse number extraction patterns
- `tests/unit/review/test_number_parsing.py` - Test pattern examples

## Implementation Requirements

### Core Functionality

1. **Pattern Detection**
   - Detect "respectively" keyword (case-insensitive)
   - Extract lists of values (percentages, currency, decimals)
   - Extract lists of periods (years, quarters, complex dates)
   - Validate equal list lengths (minimum 2 items each)
   - Return parallel associations: `[("33%", "2015"), ("35%", "2016"), ...]`

2. **Supported Pattern Types**
   - Type A: Years in preamble, values at end
     - `"Gross margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."`
   - Type B: Quarters instead of years
     - `"Revenue for Q1, Q2 and Q3 was $1M, $2M and $3M, respectively."`
   - Type C: Complex date prefixes
     - `"For the years ended December 31, 2015, 2016 and 2017 ... 33%, 35%, 43%, respectively."`
   - Type D: Values before periods
     - `"Revenue of $1M, $2M and $3M for 2015, 2016 and 2017, respectively."`

3. **Value Types to Support**
   - Percentages: `33%`, `35.0%`, `43 percent`
   - Currency: `$1M`, `$2.5 million`, `$3B`, `$50,000`
   - Plain decimals: `1.42`, `1.53`, `1.72`
   - Numbers with magnitudes: `1M`, `2.5B`, `3K`

4. **Period Types to Support**
   - Years: `2015`, `2016`, `2017` (range 1990-2029)
   - Quarters: `Q1`, `Q2`, `Q3`, `Q4`, `first quarter`, `second quarter`
   - Handle complex dates: `"December 31, 2015, 2016 and 2017"` → extract years only

5. **Confidence Scoring**
   - Base score: 0.5 (equal length requirement met)
   - +0.1 for "and" before final value
   - +0.1 for "and" before final period
   - +0.1 for consecutive years (2015, 2016, 2017)
   - +0.1 for consistent value formats (all %, all $)
   - +0.1 for close proximity (<200 chars between lists)
   - Range: 0.5 - 1.0

   **Rationale**: Weights derived from manual review of 50 SEC filing patterns. Future: replace with learned weights from `pattern_analyzer.py` (E1).

6. **Data Structure**
   ```python
   @dataclass
   class RespectivelyMatch:
       values: List[str]                # ["33%", "35%", "43%"]
       periods: List[str]               # ["2015", "2016", "2017"]
       associations: List[Tuple[str, str]]  # [("33%", "2015"), ...]
       confidence: float                # 0.5 - 1.0
       span: Tuple[int, int]           # Start and end position in text
   ```

### Error Handling

- **Invalid input** (None, empty string): Return `None` (not an error)
- **Malformed patterns**: Return `None` with `logger.debug()` message
- **Mismatched list lengths**: Return `None` (validation failure)
- **No exceptions should propagate** to caller

### Performance Requirements

- Handle segments up to 100KB without timeout
- Pattern detection completes in <100ms for typical segments (1-10KB)
- Use non-backtracking regex where possible

## Test Requirements

### Coverage Target: **≥ 90%**

### Test Categories (30+ tests recommended)

1. **Core Pattern Detection** (8-10 tests)
   - Basic year-value patterns
   - Complex date patterns ("years ended December 31...")
   - Quarter patterns (Q1, Q2, Q3)
   - Currency values with magnitudes
   - Negative cases: no "respectively", mismatched lengths, single items

2. **Value Extraction** (6-8 tests)
   - Percentages: `33%`, `35.0%`, `43 percent`
   - Currency: `$1M`, `$2.5 million`, `$50,000`
   - Plain decimals: `1.42`, `1.53`
   - List separators: `", "` and `" and "`

3. **Period Extraction** (6-8 tests)
   - Year lists: `2015, 2016, 2017`
   - Quarter lists: `Q1, Q2, Q3`
   - Complex dates: `"December 31, 2015, 2016 and 2017"`
   - Consecutive year detection

4. **Confidence Scoring** (4-6 tests)
   - High confidence (0.8+): consecutive years, clear "and", consistent formats
   - Medium confidence (0.6-0.8): some signals present
   - Low confidence (0.5): only equal length requirement

5. **Edge Cases** (4-6 tests)
   - Case insensitivity: `"Respectively"`
   - Punctuation: `"respectively."`
   - Multiple patterns in same text (return first/highest confidence)
   - Empty lists, whitespace variations

6. **Real-World Examples** (2-4 tests)
   - Farfetch Ltd S-1: LTV/CAC ratio pattern
   - Farfetch Ltd S-1: Contribution margin pattern
   - Other actual SEC filing examples

### Known False Positive Patterns to Test

1. "respectively" in legal boilerplate (no parallel lists)
2. Nested lists (years within quarters)
3. Mixed formats (some %, some $) - should return lower confidence
4. Non-metric numbers (page refs, exhibit numbers) mixed with values

## Acceptance Criteria

- [ ] New file created: `src/review/respectively_parser.py` (~150-200 lines)
- [ ] New file created: `tests/unit/review/test_respectively_parser.py` (~200+ lines)
- [ ] `detect_respectively_pattern()` function works on all 4 pattern types (A, B, C, D)
- [ ] `RespectivelyMatch` dataclass includes all required fields with validation
- [ ] **≥ 30 tests** covering core patterns, edge cases, real examples
- [ ] **Test coverage ≥ 90%** (measured by `pytest --cov`)
- [ ] All new tests pass
- [ ] `mypy src/review/respectively_parser.py --strict` passes
- [ ] NO changes to `keyword_matching.py` (L3's file)
- [ ] NO changes to `false_positive_filter.py` (L2's file)
- [ ] NO changes to `candidate_generator.py` (integration comes later)
- [ ] Full review module test suite still passes

## Do NOT

- Modify `keyword_matching.py` (L3 is working on it)
- Modify `false_positive_filter.py` (L2 is working on it)
- Modify `candidate_generator.py` (integration is a separate task)
- Add dependencies on database or other infrastructure modules
- Raise exceptions to caller (return None for invalid input)

## Integration Plan (Post-L1)

**This is NOT part of L1 implementation - reference only**

Future integration with `candidate_generator.py`:
1. Call `detect_respectively_pattern()` before standard keyword matching
2. If `RespectivelyMatch` found with confidence > 0.7:
   - Create one candidate per association
   - Set `time_period` from association tuple
   - Skip standard keyword matching for these numbers
3. If confidence < 0.7:
   - Log pattern for manual review
   - Fall back to standard keyword matching

## Verification Commands

```bash
# Run new parser tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_respectively_parser.py -v

# Check coverage (must be ≥ 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_respectively_parser.py \
  --cov=src/review/respectively_parser --cov-report=term-missing

# Type safety check
mypy src/review/respectively_parser.py --strict

# Verify no file conflicts
git diff src/review/keyword_matching.py      # Should be empty
git diff src/review/false_positive_filter.py # Should be empty

# Full review module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Real-World Validation (Post-Implementation)

1. Test against 20 Farfetch filing segments with "respectively" patterns
2. Manually verify associations match ground truth
3. Target: 95%+ precision on associations
4. Document any failures in `tests/fixtures/RESPECTIVELY_EDGE_CASES.md`

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# src/review/respectively_parser.py - Example structure only

import re
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class RespectivelyMatch:
    """Result of detecting a 'respectively' pattern."""
    values: List[str]
    periods: List[str]
    associations: List[Tuple[str, str]]
    confidence: float
    span: Tuple[int, int]

def detect_respectively_pattern(text: str) -> Optional[RespectivelyMatch]:
    """Main entry point - detect pattern and return associations."""
    # 1. Check for "respectively"
    # 2. Extract value list (working backward from "respectively")
    # 3. Extract period list (earlier in text)
    # 4. Validate equal lengths
    # 5. Create associations
    # 6. Calculate confidence
    # 7. Return RespectivelyMatch or None
    pass

def _extract_value_list(text: str) -> List[str]:
    """Extract rightmost list of values connected by ', ' or ' and '."""
    pass

def _extract_period_list(text: str) -> List[str]:
    """Extract list of time periods (years, quarters)."""
    pass

def _calculate_confidence(values: List[str], periods: List[str],
                          context: str) -> float:
    """Calculate confidence score 0.5-1.0 based on pattern signals."""
    pass
```
</details>

## Reference

- **Issue source**: `METRIC_IDENTIFICATION_ISSUES.md` Issue 3
- **Real examples**: Farfetch Ltd S-1 filing (CIK 0001740915)
- **Completion summary**: `docs/L1_COMPLETION_SUMMARY.md`

---

**Last Updated**: 2025-12-15 (marked complete)
**Format Version**: 2.0 (concise requirements-focused format)
```

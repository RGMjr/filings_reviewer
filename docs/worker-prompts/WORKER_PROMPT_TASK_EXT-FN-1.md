# WORKER PROMPT: Task EXT-FN-1 - Fix Cross-Row Exclusion Filtering for Table Metrics

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EXT-FN-1
TASK NAME:     Fix exclusion filtering to respect table row boundaries
WORKSTREAM:    Extraction Improvement
SOURCE:        Extraction Quality Analysis (2026-01-13), Updated 2026-01-14 after investigation
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (implementation 60 min, testing 90 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium - Changes exclusion logic that affects all table-based metrics
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       EXT-VAL-1 (validation improvements)
BLOCKS:        None
PARALLEL WITH: EXT-FP-1 (billings false positive fix)
═══════════════════════════════════════════════════════════════════════════════

## Objective

Fix the exclusion filtering to respect table row boundaries. Currently, `cm_large_customers_period_end` extracts only 5 of 13 gold standard values from Slack because values like 135, 298, 351 are being **incorrectly excluded** by number-context filtering that crosses row boundaries.

**Business Rationale**: Tables are the primary format for presenting time-series customer metrics in S-1 filings. Exclusion patterns from adjacent rows should not block valid candidates.

**Root Cause** (Identified 2026-01-14):
The `should_exclude_for_number_context()` method in `keyword_matching.py` checks for exclusion patterns within 100 chars of the number position, but does NOT respect table row boundaries. In the Slack filing:
```
Row 3: Paid Customers >$100,000 [CELL] 135 [CELL] 298 [CELL] 575 [CELL] 351 [CELL] 645
Row 4: Net Dollar Retention Rate [CELL] 171 [CELL] % ...
```
Values 135, 298, 575, 351, 645 are excluded because "Net Dollar Retention Rate" (in row 4) triggers the exclusion pattern `\bretention\s+rate\b` for `cm_large_customers_period_end` - even though it's in a DIFFERENT row.

**Current Behavior**:
- Keywords ARE correctly matched to values in the same row
- MarkerRowParser correctly identifies row boundaries
- BUT exclusion filtering (`should_exclude_for_number_context`) ignores row boundaries
- Result: Valid candidates are excluded due to keywords in adjacent rows

**Desired Behavior**:
- When processing table segments with [ROW]/[CELL] markers
- Exclusion filtering should only check context WITHIN the same table row
- Cross-row exclusion patterns should NOT block candidates

## Prerequisites

- Understanding of MarkerRowParser (`src/review/marker_row_parser.py`)
- Familiarity with KeywordMatcher exclusion logic (`src/review/keyword_matching.py`)
- Knowledge of [ROW]/[CELL] marker format (see CLAUDE.md design decision #16)

## Files to Read (Context Only)

- `src/review/marker_row_parser.py` - How table rows are parsed from markers (already working correctly)
- `src/review/keyword_matching.py` - Current exclusion filtering logic (needs fix)
- `src/review/candidate_generator.py` - How exclusion is called during candidate generation

## Files to Modify

1. **`src/review/keyword_matching.py`** - Add table row awareness to `should_exclude_for_number_context()`
2. **`src/review/candidate_generator.py`** - Pass table_row_parser to exclusion check
3. **`tests/unit/review/test_keyword_matching.py`** - Add tests for row-aware exclusion

## Implementation Requirements

### Core Functionality

1. **Modify `should_exclude_for_number_context()` in `keyword_matching.py`**
   - Add optional `table_row_parser` parameter
   - When parser is provided and identifies a table:
     - Get the row containing the number position
     - Limit exclusion context search to ONLY text within that row
   - When no parser or not a table: use existing 100-char window behavior (backward compatible)

2. **Pass table_row_parser to exclusion check in `candidate_generator.py`**
   - In `_process_segment()`, the `table_row_parser` is already created at line 583-592
   - Pass it to `should_exclude_for_number_context()` when calling at line 651-656
   - This is a minimal change - just threading an existing variable through

3. **Maintain Existing Behavior**
   - Non-table segments should work exactly as before (no parser passed)
   - Tables without markers use TableRowParser with same logic
   - Inline text matches unchanged

### Specific False Negative Examples to Fix

From Slack gold standard - these values are currently being incorrectly excluded:

| Value | Row | Excluded By | Reason |
|-------|-----|-------------|--------|
| 135 | "Paid Customers >$100,000" | "Net Dollar Retention Rate" (row 4) | `\bretention\s+rate\b` pattern |
| 298 | "Paid Customers >$100,000" | "Net Dollar Retention Rate" (row 4) | `\bretention\s+rate\b` pattern |
| 575 | "Paid Customers >$100,000" | "Net Dollar Retention Rate" (row 4) | `\bretention\s+rate\b` pattern |
| 351 | "Paid Customers >$100,000" | "Net Dollar Retention Rate" (row 4) | `\bretention\s+rate\b` pattern |
| 645 | "Paid Customers >$100,000" | "Net Dollar Retention Rate" (row 4) | `\bretention\s+rate\b` pattern |

Sample table segment structure:
```
Row 3: Paid Customers >$100,000 [CELL] 135 [CELL] 298 [CELL] 575 [CELL] 351 [CELL] 645
Row 4: Net Dollar Retention Rate [CELL] 171 [CELL] % [CELL] 152 [CELL] % ...
```

After fix: Values 135, 298, 575, 351, 645 should NOT be excluded because "Net Dollar Retention Rate" is in a DIFFERENT row.

### Error Handling

- **No table parser**: Fall back to existing 100-char window behavior
- **Position not in any row**: Fall back to existing behavior (conservative)
- **Empty row text**: Skip exclusion check for that number

## Test Requirements

### Coverage Target: **≥85%** for modified exclusion logic

### Test Categories (12+ tests recommended)

1. **Row-Aware Exclusion Filtering** (5-6 tests)
   - Exclusion pattern in SAME row → should exclude
   - Exclusion pattern in DIFFERENT row → should NOT exclude
   - Multiple exclusion patterns, one in same row, one in different → should exclude
   - No table parser provided → fall back to 100-char window (existing behavior)
   - Table parser provided but position not in any row → fall back to existing behavior

2. **Integration with MarkerRowParser** (3-4 tests)
   - MarkerRowParser correctly limits context to row text
   - TableRowParser (HTML-based) correctly limits context to row text
   - Works with both parser types interchangeably

3. **Regression Tests** (3-4 tests)
   - Non-table segments still use 100-char window
   - Exclusion patterns that ARE within same row still trigger exclusion
   - Existing test cases still pass

### Specific Test Case (from Slack filing)

```python
def test_exclusion_respects_table_row_boundaries():
    """Values in 'Paid Customers >$100,000' row should not be excluded by 'Net Dollar Retention Rate' in adjacent row."""
    text = "Paid Customers >$100,000 [CELL] 135 [CELL] 298 [ROW] Net Dollar Retention Rate [CELL] 171 [CELL] %"
    parser = MarkerRowParser(text)

    # Position of "135" is in row with "Paid Customers >$100,000"
    # "Net Dollar Retention Rate" is in a DIFFERENT row
    # Exclusion pattern "\bretention\s+rate\b" should NOT match for cm_large_customers_period_end

    should_exclude, reason = matcher.should_exclude_for_number_context(
        metric_id="cm_large_customers_period_end",
        text=text,
        number_position=32,  # position of "135"
        table_row_parser=parser,
    )
    assert should_exclude is False  # NOT excluded because "retention rate" is in different row
```

## Gold Standard Validation

This task modifies `src/review/keyword_matching.py` and `src/review/candidate_generator.py`. Gold standard validation is **required** before commit.

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --company "Slack" --mode fresh --baseline

# Verify cm_large_customers_period_end candidates increased (target: ≥10, currently 5)
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer && python3 << 'EOF'
from src.extraction.html_segmenter import segment_filing_html
from src.review.candidate_generator import CandidateGenerator

segments = segment_filing_html(999, 'data/gold_standard/Slack_Technologies/filing.html')
segment_dicts = [s.to_dict() for s in segments]
generator = CandidateGenerator()
candidates = generator.generate_for_filing(999, 999, segment_dicts)

large_cust = [c for c in candidates if c.suggested_metric_id == 'cm_large_customers_period_end']
print(f'cm_large_customers_period_end candidates: {len(large_cust)} (target: ≥10, was 5)')
for c in large_cust:
    print(f'  {c.raw_number_text}')

# Verify the specific missing values are now present
target_values = {'135', '298', '351', '575', '645'}
found_values = {c.raw_number_text for c in large_cust}
missing = target_values - found_values
if missing:
    print(f'\n❌ Still missing: {missing}')
else:
    print(f'\n✅ All target values found!')
EOF
```

## Acceptance Criteria

- [ ] `should_exclude_for_number_context()` accepts optional `table_row_parser` parameter
- [ ] When table parser provided, exclusion context limited to same row
- [ ] When no table parser, existing 100-char window behavior preserved
- [ ] Slack `cm_large_customers_period_end` candidates increased from 5 to ≥10
- [ ] Missing values 135, 298, 351, 575, 645 are now extracted
- [ ] No regression in existing non-table extraction
- [ ] **12+ unit tests** covering row-aware exclusion scenarios
- [ ] **Test coverage ≥85%** for modified code
- [ ] All existing tests still pass
- [ ] Gold standard recall improves for Slack

## Do NOT

- Modify `src/extraction/html_segmenter.py` - marker format is stable
- Change the [ROW]/[CELL] marker syntax
- Change the exclusion patterns themselves - only WHERE they're checked
- Break existing inline text matching behavior
- Add dependencies on external libraries

## Verification Commands

```bash
# Run keyword matching tests (new tests go here)
python3 -m pytest tests/unit/review/test_keyword_matching.py -v

# Run candidate generator tests
python3 -m pytest tests/unit/review/test_candidate_generator.py -v

# Check coverage for modified files
python3 -m pytest tests/unit/review/test_keyword_matching.py \
  --cov=src/review/keyword_matching --cov-report=term-missing

# Run gold standard validation
python scripts/validate_against_gold_standard.py --company "Slack" --mode fresh

# Full test suite
python3 -m pytest tests/unit/ --no-cov -q
```

## Critical Evaluation Phase

**Required for all tasks. Depth: M (Standard review)**

After verification passes but BEFORE committing:
1. Code Quality Review - Is row-aware exclusion cleanly integrated?
2. Test Coverage Assessment - Are edge cases (no parser, position not in row) covered?
3. Architecture Alignment - Does parameter threading follow existing patterns?
4. **User Approval (REQUIRED)** - STOP and ask user before committing

## Expected Impact

**Before EXT-FN-1**:
- cm_large_customers_period_end candidates: 5
- Values 135, 298, 351, 575, 645 incorrectly excluded by cross-row "retention rate" pattern

**After EXT-FN-1**:
- cm_large_customers_period_end candidates: ≥10
- All 5 missing values (135, 298, 351, 575, 645) now extracted
- Similar improvements expected for other table-based metrics affected by cross-row exclusion

## Reference

- **Issue source**: Extraction Quality Analysis (2026-01-13)
- **Root cause investigation**: 2026-01-14 (confirmed exclusion filtering issue, not keyword matching)
- **Dependencies**: None
- **Related**: HRV-17 (table row parsing fix - already complete), EA-3 (table-aware context)

---

**Last Updated**: 2026-01-14
**Format Version**: 2.6

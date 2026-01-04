# WORKER PROMPT: Task HRV-17 - Table Row Parsing Fix

```
===============================================================================
TASK ID:       HRV-17
TASK NAME:     Fix incomplete table row parsing in TableRowParser
WORKSTREAM:    Human Review Validation
SOURCE:        Investigation from HRV-15 (Farfetch recall: 23.9% due to row mapping failures)
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3-4 hours (investigation 1h, implementation 1.5h, testing 1h)
TIME ACTUAL:   N/A
RISK LEVEL:    MEDIUM - Changes affect cross-row validation which prevents false positives
               - Risk: Overly permissive fix could allow cross-row matches (historical issue)
               - Risk: Overly strict fix maintains current recall loss
               - Impact: False positives confuse reviewers; false negatives miss valid candidates
               - Mitigation: Comprehensive test coverage for edge cases
TASK SIZE:     M
DEPENDS ON:    None (standalone investigation)
UNLOCKS:       HRV-16 (Validation re-run with improved parsing)
BLOCKS:        None
PARALLEL WITH: HRV-12 (no file conflicts)
===============================================================================
```

## Objective

Fix the incomplete row mapping in `TableRowParser` that causes valid candidates to be filtered out when `are_in_same_row()` cannot determine row membership for positions in unmapped regions of table text.

**Business Rationale**: Farfetch filing recall is 23.9% (vs 86.4% for Slack) because ~26% of table text positions are unmapped. Valid candidates (AOV, LTV/CAC) in unmapped regions are incorrectly filtered out.

**Current Behavior**:
- `_parse_rows()` maps rows 0-528 of 716-char table text (positions 529-716 unmapped)
- `get_row_at_position()` returns `None` for unmapped positions
- `are_in_same_row()` returns `False` when either position is unmapped
- Valid keyword-value pairs in unmapped regions are filtered out

**Desired Behavior**:
- `_parse_rows()` correctly maps all table rows (100% coverage or graceful fallback)
- `are_in_same_row()` accurately determines row membership for all positions
- No valid candidates lost due to parsing failures
- No cross-row matches allowed (maintain precision)

## Prerequisites

- Understanding of HTML table structure parsing
- Understanding of how `HTMLSegmenter` extracts text from tables
- Familiarity with BeautifulSoup HTML parsing

## Files to Read (Context Only)

- `src/review/table_structure.py` - Current implementation to fix
- `src/extraction/html_segmenter.py` - How text is extracted from HTML tables
- `src/review/candidate_generator.py` - How `TableRowParser` is used (lines ~180-220)

## Files to Modify

1. **`src/review/table_structure.py`** - Fix `_parse_rows()` algorithm and related methods
2. **`tests/unit/review/test_table_structure.py`** - Add comprehensive tests (may need to create)

## Implementation Requirements

### Core Functionality

1. **Root Cause Investigation**
   - Identify why `_parse_rows()` fails to map positions 529-716 in Farfetch segment 25861
   - Compare row text from `tr.get_text()` vs actual extracted text
   - Check for whitespace normalization differences between parsing and extraction
   - Document the failure mode(s)

2. **Fix Row Mapping Algorithm**
   - Ensure all table rows are correctly mapped to text positions
   - Handle whitespace normalization differences between HTML parsing and text extraction
   - Handle edge cases: nested tables, empty cells, colspan/rowspan
   - Add fallback for rows that can't be exactly matched

3. **Fallback Strategy** (if 100% mapping not achievable)
   - If row cannot be mapped, extend previous row's boundary OR create gap-filling row
   - Ensure no text positions are left unmapped
   - Log warnings for unmapped regions (TRS-2 prefix)

4. **Maintain Cross-Row Protection**
   - `are_in_same_row()` must still return `False` for positions in different rows
   - Only return `True` when positions are provably in the same row
   - Document any uncertainty in return value semantics

### Error Handling

- **Unparseable HTML**: Return single-row fallback (entire text as one row)
- **Normalization mismatches**: Use fuzzy matching with configurable tolerance
- **Nested tables**: Flatten to linear row sequence

### Performance Requirements

- Parsing must complete in <10ms for typical table segments
- No regex backtracking that could cause exponential time

## Test Requirements

### Coverage Target: **>= 90%** for `src/review/table_structure.py`

### Test Categories (20+ tests recommended)

1. **Basic Row Mapping** (5-7 tests)
   - Simple table: 3 rows, 2 columns
   - Table with header row (`<th>` elements)
   - Table with empty cells
   - Table with varying column counts per row

2. **Whitespace Edge Cases** (4-6 tests)
   - Multiple spaces in cells vs normalized single space
   - Newlines within cells
   - Leading/trailing whitespace in cells
   - Non-breaking spaces (&nbsp;)

3. **Position Mapping Accuracy** (4-6 tests)
   - First character of each row maps correctly
   - Last character of each row maps correctly
   - Characters at row boundaries
   - Characters in the middle of cells

4. **are_in_same_row() Correctness** (4-6 tests)
   - Two positions in same row -> True
   - Two positions in different rows -> False
   - Position at exact row boundary
   - Positions in first and last rows

5. **Fallback/Edge Cases** (3-5 tests)
   - HTML without table -> single row covering all text
   - Nested tables
   - Table with colspan/rowspan attributes
   - Very long row text that wraps

### Known Edge Cases to Test

- Farfetch segment 25861: 716 chars, 11+ rows, currently only maps positions 0-528
- Tables where row text appears multiple times (duplicate content)
- Tables with percentage symbols and currency in same row

## Gold Standard Validation

This task affects candidate filtering logic. Gold standard validation is **required** before commit.

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --company "Farfetch" --mode db

# Formal validation (must pass before commit)
pytest -m gold_standard --gold-standard-mode=fresh -v
```

### Regression Handling

- Farfetch recall should improve from 23.9% toward 50%+
- Farfetch precision should remain high (currently 100%)
- If precision drops significantly, investigate for cross-row matches

## Acceptance Criteria

- [ ] Root cause documented (why rows 529-716 unmapped)
- [ ] `_parse_rows()` maps 100% of text positions (or documents why not)
- [ ] All Farfetch table segments have full row coverage
- [ ] `are_in_same_row()` never returns True for cross-row pairs
- [ ] **20+ unit tests** covering all test categories
- [ ] **Test coverage >= 90%** for table_structure.py
- [ ] Farfetch recall improves (target: 50%+, was 23.9%)
- [ ] Farfetch precision remains high (target: >80%, was 100%)
- [ ] All existing tests pass
- [ ] `mypy src/review/table_structure.py --strict` passes

## Do NOT

- Change `are_in_same_row()` to return `True` when row cannot be determined (this was tried and reverted - causes cross-row false positives)
- Modify `src/extraction/html_segmenter.py` (extraction is working correctly)
- Add dependencies on external HTML parsing libraries beyond BeautifulSoup
- Change the public API of `TableRowParser`

## Verification Commands

```bash
# Run table_structure tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_table_structure.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_table_structure.py \
  --cov=src/review/table_structure --cov-report=term-missing

# Type check
mypy src/review/table_structure.py --strict

# Validate against gold standard
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_against_gold_standard.py --company "Farfetch" --mode db
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task HRV-17: Table Row Parsing Fix
# Run: bash verify_hrv17.sh

set -e
echo "==============================================================================="
echo "Verifying Task HRV-17: Table Row Parsing Fix"
echo "==============================================================================="

# Check type safety
echo "Checking: mypy passes..."
mypy src/review/table_structure.py --strict

# Run tests with coverage
echo "Checking: Test coverage >= 90%..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_table_structure.py \
  --cov=src/review/table_structure --cov-report=term --cov-fail-under=90 -q

# Validate gold standard
echo "Checking: Farfetch recall improvement..."
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_against_gold_standard.py --company "Farfetch" --mode db

# Full test suite regression
echo "Running full review test suite..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q

echo "==============================================================================="
echo "All acceptance criteria verified for Task HRV-17!"
echo "==============================================================================="
```

## Critical Evaluation Phase

**Required for all tasks. Depth: M (Thorough evaluation)**

After verification passes but BEFORE committing:

1. **Code Quality Review**
   - [ ] No linting issues or type errors
   - [ ] DRY principle followed
   - [ ] Naming conventions match project standards
   - [ ] Error handling is appropriate

2. **Test Coverage Assessment**
   - [ ] All edge cases from requirements covered
   - [ ] Negative test cases exist
   - [ ] Integration with candidate_generator tested

3. **Architecture Alignment**
   - [ ] Solution follows patterns in CLAUDE.md
   - [ ] Conservative approach maintained (no cross-row matches)
   - [ ] Changes are minimal and focused

4. **Identify Improvements**
   - Document any potential improvements for follow-up tasks

5. **User Approval (REQUIRED)**
   - STOP and ask user before committing

## Expected Impact

**Before HRV-17**:
- Farfetch recall: 23.9%
- Farfetch precision: 100%
- Farfetch F1: 38.6%
- Root cause: ~26% of table text unmapped

**After HRV-17**:
- Farfetch recall: 50%+ (target)
- Farfetch precision: >80% (target)
- Farfetch F1: 60%+ (estimated)
- Full row coverage for all table segments

## Reference

- **Issue source**: HRV-15 investigation (Farfetch false negatives)
- **Related tasks**: HRV-16 (Validation re-run after fix)
- **Historical context**: A previous attempt to fix this by making `are_in_same_row()` return `True` for unmapped positions was reverted because it caused cross-row false positives

---

**Last Updated**: 2026-01-03
**Format Version**: 2.6

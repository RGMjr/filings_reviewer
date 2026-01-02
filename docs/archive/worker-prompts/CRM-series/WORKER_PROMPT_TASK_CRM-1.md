# WORKER PROMPT: Task CRM-1 - Create MarkerRowParser Class

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       CRM-1
TASK NAME:     Create MarkerRowParser for [ROW]/[CELL] marker parsing
WORKSTREAM:    Review System Improvements
SOURCE:        Cross-row matching diagnosis (2025-12-31)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-1.5 hours (implementation 45 min, tests 45 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (new isolated class, no existing code modified)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       CRM-2
BLOCKS:        CRM-2
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create a lightweight parser that extracts table row boundaries from `[ROW]`/`[CELL]` markers in pre-processed text, enabling accurate same-row detection for keyword matching.

**Business Rationale**: Currently, 252 false positive candidates are generated because values in tables are incorrectly matched to keywords from different rows. This parser will enable accurate row boundary detection from marker-encoded text.

**Current Behavior**: `TableRowParser` fails when text contains `[ROW]`/`[CELL]` markers because it expects raw HTML text format.

**Desired Behavior**: A new `MarkerRowParser` class correctly parses row boundaries from marker-encoded text.

## Prerequisites

- None (standalone task)

## Files to Create

1. **`src/review/marker_row_parser.py`** - Lightweight marker-based row parser
2. **`tests/unit/review/test_marker_row_parser.py`** - Comprehensive unit tests

## Files to Read (Context Only)

- `src/review/table_structure.py` - Existing TableRowParser API to match (duck typing compatibility)
- `src/extraction/html_segmenter.py:1051-1124` - Marker format reference (`[CELL]` between cells, `[ROW]` between rows)

## Implementation Requirements

### Core Functionality

1. **Row Boundary Parsing**
   - Split text on `" [ROW] "` markers to identify row boundaries
   - Track start/end character positions for each row
   - Handle first row (no leading `[ROW]` marker)
   - Handle empty rows gracefully

2. **Same-Row Detection** (`are_in_same_row(pos1, pos2)`)
   - Return `True` if both positions are in the same row
   - Return `False` if positions are in different rows
   - Return `False` if either position cannot be mapped (strict mode)

3. **Row Heading Detection** (`is_row_heading(position)`)
   - Header is text before first `[CELL]` marker in each row
   - Numeric-only headers (e.g., "2023") are NOT treated as headers
   - Return `True` if position is within a detected header

4. **Table Detection** (`is_table()`)
   - Return `True` if 2+ rows detected
   - Return `False` for single row or empty text

5. **Data Structure**
   ```python
   @dataclass
   class MarkerRow:
       row_index: int       # 0-based row number
       text_start: int      # Character position where row starts
       text_end: int        # Character position where row ends (exclusive)
       row_text: str        # Actual text content of the row
       header_text: str | None = None
       header_start: int | None = None
       header_end: int | None = None
   ```

### Error Handling

- **Empty text**: Return empty rows list, `is_table()` returns False
- **No markers**: Treat entire text as single row
- **Position out of range**: `are_in_same_row()` returns False

## Test Requirements

### Coverage Target: **≥ 90%** for `src/review/marker_row_parser.py`

### Test Categories (15+ tests recommended)

1. **Basic Parsing** (3-4 tests)
   - Two-row table with markers
   - Single row (no `[ROW]` marker)
   - Multiple rows with varying cell counts

2. **Same-Row Detection** (4-5 tests)
   - Two positions in same row → True
   - Two positions in different rows → False
   - Position at row boundary
   - Position out of range → False

3. **Header Detection** (3-4 tests)
   - Non-numeric first cell is header
   - Numeric-only first cell NOT a header (e.g., "2023")
   - Mixed alphanumeric IS a header (e.g., "$100K ARR")
   - Single-cell row header detection

4. **Edge Cases** (4-5 tests)
   - Empty text
   - Whitespace-only text
   - Only `[CELL]` markers (no `[ROW]`)
   - Text with markers but no table structure

### Known Edge Cases to Test

- Row with only numeric cells (no meaningful header)
- Position exactly at `[ROW]` marker boundary
- Very long rows (1000+ characters)

## Acceptance Criteria

- [ ] `MarkerRowParser` class with `__init__(marked_text: str)`
- [ ] `are_in_same_row(pos1: int, pos2: int) -> bool` method
- [ ] `is_row_heading(position: int) -> bool` method
- [ ] `is_table() -> bool` method
- [ ] `get_rows() -> list[MarkerRow]` method
- [ ] **15+ unit tests** covering all test categories
- [ ] **Test coverage ≥ 90%** for the module
- [ ] All tests pass
- [ ] `mypy src/review/marker_row_parser.py --strict` passes

## Do NOT

- Modify `src/review/table_structure.py` (keep existing parser unchanged)
- Modify `src/review/candidate_generator.py` (that's CRM-2)
- Add dependencies on external packages (use only stdlib + dataclasses)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_marker_row_parser.py -v

# Check coverage (must be ≥ 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_marker_row_parser.py \
  --cov=src/review/marker_row_parser --cov-report=term-missing --cov-fail-under=90

# Type safety check
mypy src/review/marker_row_parser.py --strict
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task CRM-1: MarkerRowParser
set -e

echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task CRM-1: Create MarkerRowParser Class"
echo "═══════════════════════════════════════════════════════════════"

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check file exists
echo "✓ Checking: marker_row_parser.py exists..."
test -f src/review/marker_row_parser.py

# Check test file exists
echo "✓ Checking: test_marker_row_parser.py exists..."
test -f tests/unit/review/test_marker_row_parser.py

# Type safety
echo "✓ Checking: mypy passes..."
mypy src/review/marker_row_parser.py --strict

# Tests + Coverage
echo "✓ Checking: Tests pass with ≥90% coverage..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_marker_row_parser.py \
  --cov=src/review/marker_row_parser --cov-report=term-missing --cov-fail-under=90 -v

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task CRM-1!"
echo "═══════════════════════════════════════════════════════════════"
```

## Reference

- **Issue source**: Cross-row matching diagnosis, 252 "not_a_metric" false positives
- **Dependencies**: None
- **Related**: CRM-2 (integration task)

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4

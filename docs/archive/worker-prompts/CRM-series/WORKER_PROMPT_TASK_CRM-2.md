# WORKER PROMPT: Task CRM-2 - Integrate MarkerRowParser into CandidateGenerator

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       CRM-2
TASK NAME:     Integrate MarkerRowParser in candidate generation pipeline
WORKSTREAM:    Review System Improvements
SOURCE:        Cross-row matching diagnosis (2025-12-31)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 15-30 minutes
TIME ACTUAL:   N/A
RISK LEVEL:    Low (small conditional change, fallback preserved)
TASK SIZE:     XS
DEPENDS ON:    CRM-1
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Use `MarkerRowParser` when segment text contains `[ROW]`/`[CELL]` markers, falling back to `TableRowParser` when no markers are present.

**Business Rationale**: This enables the cross-row matching fix to take effect in the candidate generation pipeline, preventing the 252 false positive candidates identified in diagnosis.

**Current Behavior**: `CandidateGenerator` always uses `TableRowParser` which fails on marker-encoded text.

**Desired Behavior**: `CandidateGenerator` detects markers and uses the appropriate parser.

## Prerequisites

- CRM-1 complete (`MarkerRowParser` class exists and tests pass)

## Files to Modify

1. **`src/review/candidate_generator.py`** - Add conditional parser selection (~6 lines)

## Files to Read (Context Only)

- `src/review/marker_row_parser.py` - New parser class (CRM-1 output)
- `src/review/table_structure.py` - Existing TableRowParser for fallback

## Implementation Requirements

### Core Functionality

1. **Marker Detection**
   - Check if segment text contains `" [ROW] "` or `" [CELL] "` markers
   - This check should come BEFORE the HTML table check

2. **Parser Selection**
   - If markers present: Use `MarkerRowParser(text)`
   - If no markers but HTML table: Use `TableRowParser(raw_html, text)`
   - If neither: `table_row_parser` remains `None`

3. **Location**: Lines ~575-587 in `_process_segment()` method

### Code Change

Replace this block (approximately lines 575-587):
```python
table_row_parser = None
raw_html = segment.get("raw_html", "")
if raw_html and ('<table' in raw_html.lower()):
    from src.review.table_structure import TableRowParser
    table_row_parser = TableRowParser(raw_html, text)
```

With:
```python
table_row_parser = None
raw_html = segment.get("raw_html", "")

# Check for markers first (more reliable when present)
if " [ROW] " in text or " [CELL] " in text:
    from src.review.marker_row_parser import MarkerRowParser
    table_row_parser = MarkerRowParser(text)
elif raw_html and ('<table' in raw_html.lower()):
    from src.review.table_structure import TableRowParser
    table_row_parser = TableRowParser(raw_html, text)
```

### API Compatibility

No changes needed to `KeywordMatcher` - both parsers implement the same duck-typed interface:
- `are_in_same_row(pos1, pos2)`
- `is_row_heading(position)`
- `is_table()`

## Test Requirements

### Coverage: Maintain existing coverage for `candidate_generator.py`

### Validation (no new tests required)

1. **Existing tests must pass** - Verifies no regression
2. **Integration tests must pass** - Verifies end-to-end behavior

## Acceptance Criteria

- [ ] `MarkerRowParser` imported and used when markers detected
- [ ] `TableRowParser` used as fallback when no markers
- [ ] All existing tests in `tests/unit/review/test_candidate_generator.py` pass
- [ ] All tests in `tests/integration/test_e2_candidate_filtering.py` pass
- [ ] No changes to `KeywordMatcher` required

## Do NOT

- Modify `MarkerRowParser` class (CRM-1 handles that)
- Modify `KeywordMatcher` (duck typing means no changes needed)
- Add new tests (existing tests validate the integration)
- Change the interface or behavior of `_process_segment()` beyond parser selection

## Verification Commands

```bash
# Run candidate generator unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py -v --tb=short

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -v --tb=short

# Run all review tests (regression check)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task CRM-2: Integrate MarkerRowParser
set -e

echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task CRM-2: Integrate MarkerRowParser"
echo "═══════════════════════════════════════════════════════════════"

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check MarkerRowParser import exists in candidate_generator.py
echo "✓ Checking: MarkerRowParser imported in candidate_generator.py..."
grep -q "from src.review.marker_row_parser import MarkerRowParser" src/review/candidate_generator.py

# Check marker detection logic exists
echo "✓ Checking: Marker detection logic exists..."
grep -q '\[ROW\]' src/review/candidate_generator.py

# Run unit tests
echo "✓ Checking: Unit tests pass..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py --no-cov -q

# Run integration tests
echo "✓ Checking: Integration tests pass..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task CRM-2!"
echo "═══════════════════════════════════════════════════════════════"
```

## Reference

- **Issue source**: Cross-row matching diagnosis, 252 "not_a_metric" false positives
- **Dependencies**: CRM-1 (must complete first)
- **Related**: Table structure parsing in review system

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4

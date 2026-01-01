# WORKER PROMPT: Task EI-3 - Integrate FalsePositiveFilter in ValueExtractor

```
===============================================================================
TASK ID:       EI-3
TASK NAME:     Integrate FalsePositiveFilter into ValueExtractor extraction methods
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 - Issue #3
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-3_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 3-4 hours (implementation 90 min, testing 90-120 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Reusing proven component from CandidateGenerator
               - Risk: NumberMatch creation requires text positions; ValueExtractor
                 may not track positions for all extracted numbers
               - Impact: If filter can't be applied, false positives remain
               - Likelihood: Low (extraction methods track number positions)
               - Mitigation: Graceful fallback when position unavailable
PARALLEL WITH: EI-1, EI-2 (all independent Phase 1 tasks)
===============================================================================
```

## Objective

Apply the same false positive filtering used in CandidateGenerator to ValueExtractor, preventing page numbers, years, TOC references, and dates from being extracted as metric values.

**Business Rationale**: ValueExtractor currently extracts all numbers without filtering, including page numbers (e.g., "page 23"), years (e.g., "2019"), and TOC references. These pollute the `metric_values` table and waste analyst time when reviewing extraction results.

**Current Behavior**: ValueExtractor extracts page numbers, years, dates, TOC references as metric values. Example: A filing segment like "Revenue grew 15% from 2019 to 2023 (see page 45)" would extract "2019", "2023", and "45" as metric values alongside the legitimate "15%".

**Desired Behavior**: ValueExtractor applies FalsePositiveFilter before creating MetricValue objects, same as CandidateGenerator. Only legitimate metric values are stored.

## Prerequisites

- None (FalsePositiveFilter already exists and is proven in CandidateGenerator)
- Recommended: EI-2 complete (measurement unit patterns add value to filter)
- Understand `FalsePositiveFilter.is_false_positive()` method signature and `NumberMatch` dataclass

## Files to Modify

1. **`src/extraction/value_extractor.py`** - Import and integrate FalsePositiveFilter in `__init__` and all extraction methods

## Files to Read (Context Only)

- `src/review/false_positive_filter.py` - Understand FalsePositiveFilter API (lines 381-466 show `is_false_positive()`)
- `src/review/number_parsing.py` - Understand NumberMatch dataclass (lines 107-115)
- `src/review/candidate_generator.py` - See how it uses FalsePositiveFilter (look for `is_false_positive` calls)
- `tests/unit/extraction/test_value_extractor.py` - Understand existing test patterns

## Implementation Requirements

### Core Functionality

1. **Import and Initialize Filter**
   - Import `FalsePositiveFilter` from `src.review.false_positive_filter`
   - Import `NumberMatch` from `src.review.number_parsing`
   - Initialize `self._fp_filter = FalsePositiveFilter()` in `__init__` (around line 296)
   - Use default filter settings (proven in CandidateGenerator)

2. **Create Helper Method for Filter Application**
   - Add `_is_false_positive_value()` helper method to encapsulate filter logic
   - Method should create a `NumberMatch` from value string and position
   - Return tuple `(is_false_positive: bool, reason: Optional[str])`
   - Handle cases where position information is not available

3. **Apply Filter in `extract_from_text()` (line ~409)**
   - After finding numbers with `NUMBER_PATTERN` regex
   - Before creating MetricValue, check if value is false positive
   - Skip false positives with DEBUG log message
   - Track filtered count in method for debugging

4. **Apply Filter in `extract_from_table()` (line ~353)**
   - During `_parse_table_row()` processing or after parsing numeric values
   - For each numeric value before creating MetricValue
   - Use cell text context for false positive detection
   - Skip false positives with DEBUG log message

5. **Apply Filter in `extract_from_text_with_llm()` (line ~457)**
   - After LLM returns candidate values
   - Validate each value against filter before creating MetricValue
   - Use segment.raw_text as context for filter

6. **Apply Filter in `extract_from_table_with_llm()` (line ~614)**
   - After LLM returns candidate values from table
   - Validate each value against filter before creating MetricValue
   - Use segment.raw_text as context for filter

### Helper Method Specification

```python
def _is_false_positive_value(
    self,
    value_str: str,
    position: Optional[int],
    context_text: str,
    unit: Optional[str] = None
) -> Tuple[bool, Optional[str]]:
    """
    Check if an extracted value is a false positive.

    Args:
        value_str: The raw value string (e.g., "2019", "45")
        position: Character position in context_text (None if unknown)
        context_text: The full text containing the value
        unit: Optional unit type ('count', 'currency', 'percentage')

    Returns:
        Tuple of (is_false_positive, reason_string)
    """
    # Implementation should:
    # 1. Create NumberMatch with position info
    # 2. Call self._fp_filter.is_false_positive()
    # 3. Return result with logging
```

### Error Handling

- **Filter initialization fails**: Log warning at startup, set `_fp_filter = None`, extraction continues without filtering
- **Position not found in text**: Log DEBUG warning, proceed without filtering for that value (don't block extraction)
- **NumberMatch creation fails**: Log warning, proceed without filtering (don't block extraction)
- **Filter exception during check**: Log warning, proceed without filtering (don't break extraction)
- **No exceptions should propagate**: Extraction must complete even if filtering fails

### Performance Requirements

- Filter check adds ~1-2ms per number (negligible for typical segments)
- No significant performance impact expected (<5% overhead on extraction methods)
- Filter is already optimized in CandidateGenerator

### Backward Compatibility

- **API Changes**: None - public method signatures unchanged
- **Existing callers**: Continue to work; they'll get filtered (improved) results
- **Data Format Changes**: None - MetricValue structure unchanged
- **Feature Flags**: Not needed - filtering improves quality universally

## Test Requirements

### Coverage Target: **Maintain ≥85%** for `src/extraction/value_extractor.py`

### Test Categories (12-15 tests recommended)

1. **False Positive Filtering - Years** (3 tests)
   - `test_year_in_text_filtered` - "revenue grew from 2019 to 2023" should not extract 2019 or 2023
   - `test_year_in_table_filtered` - Table cell with year alone should be filtered
   - `test_year_like_value_not_filtered` - "$2,019" (currency) should NOT be filtered (it's not a year)

2. **False Positive Filtering - Page/Reference Numbers** (3 tests)
   - `test_page_number_filtered` - "see page 45" should not extract 45
   - `test_note_reference_filtered` - "Note 12" should not extract 12
   - `test_section_reference_filtered` - "Section 5.2" should not extract 5

3. **False Positive Filtering - TOC References** (2 tests)
   - `test_toc_proximity_filtered` - Number near "Table of Contents" filtered
   - `test_dot_leader_filtered` - "Risk Factors...........23" should not extract 23

4. **False Positive Filtering - Dates** (2 tests)
   - `test_date_component_filtered` - "December 31, 2023" should not extract 31
   - `test_date_in_context_filtered` - "as of January 1, 2024" should not extract components

5. **Legitimate Values Pass Through** (3 tests)
   - `test_metric_value_not_filtered` - "24,000 customers" should extract 24000
   - `test_percentage_not_filtered` - "grew 15% year over year" should extract 15
   - `test_currency_value_not_filtered` - "revenue of $50 million" should extract 50000000

6. **Error Handling** (2-3 tests)
   - `test_missing_position_handled` - Extraction works when position unavailable
   - `test_filter_exception_handled` - Extraction continues if filter raises exception
   - `test_filter_not_available_handled` - Extraction works if filter initialization fails

### Test File Location

Add tests to: `tests/unit/extraction/test_value_extractor.py`

### Test Class Name

```python
class TestFalsePositiveFiltering:
    """EI-3: False positive filtering integration tests."""

    def test_year_filtered_from_text_extraction(self):
        """Years like 2019, 2023 should be filtered from extraction."""
        ...

    def test_page_number_filtered(self):
        """Page references like 'page 45' should be filtered."""
        ...

    def test_legitimate_metric_value_not_filtered(self):
        """Real metric values like '24,000 customers' should pass through."""
        ...
```

## Acceptance Criteria

- [ ] FalsePositiveFilter imported and initialized in `__init__`
- [ ] `_is_false_positive_value()` helper method created
- [ ] Filter applied in `extract_from_text()`
- [ ] Filter applied in `extract_from_table()`
- [ ] Filter applied in `extract_from_text_with_llm()`
- [ ] Filter applied in `extract_from_table_with_llm()`
- [ ] Years (1990-2100) excluded from extraction
- [ ] Page/note/section references excluded from extraction
- [ ] TOC references excluded from extraction
- [ ] Date components excluded from extraction
- [ ] Legitimate metric values still extracted correctly
- [ ] 12+ unit tests covering all filter types and edge cases
- [ ] Coverage maintained ≥85% for `value_extractor.py`
- [ ] All existing tests still pass (no regressions)
- [ ] `mypy src/extraction/value_extractor.py` passes (type hints for new code)
- [ ] NO changes to FalsePositiveFilter itself

## Do NOT

- Modify `false_positive_filter.py` (reuse as-is)
- Modify `number_parsing.py` (reuse as-is)
- Add new filter types or patterns (use existing filter)
- Change MetricValue data structure
- Change extraction logic beyond adding filter checks
- Break existing LLM extraction functionality
- Raise exceptions that propagate to callers (handle all errors gracefully)
- Add configuration parameters for enabling/disabling filter (always-on improves quality)

## Verification Commands

```bash
# Run new tests specifically
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py::TestFalsePositiveFiltering -v

# Verify no regressions in value extractor tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py --no-cov -q

# Check coverage is maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py \
  --cov=src/extraction/value_extractor --cov-report=term-missing -q

# Type safety check (for new code)
mypy src/extraction/value_extractor.py

# Full extraction module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q

# Verify filter module still works (dependency)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py --no-cov -q
```

## Expected Impact

**Before EI-3**:
- "Page 23" extracted as metric value 23
- Year "2019" extracted as metric value 2019
- TOC reference ".....................73" extracted as value 73
- Date component "31" from "December 31" extracted as value
- ~20-30% of extracted values are false positives

**After EI-3**:
- Page numbers, years, TOC refs, date components filtered out
- Only legitimate metric values (customer counts, revenue, percentages) extracted
- Estimated 80% reduction in false positive extractions
- Improved data quality for downstream analysis

## Post-Implementation Tasks

After completing EI-3:

1. **Create Completion Summary**:
   - Create `docs/completion/EI-3_COMPLETION_SUMMARY.md` with:
     - Summary of changes made
     - Test results and coverage
     - Any deviations from plan
     - Before/after false positive counts if measured
     - Commit hash

2. **Update Documentation**:
   - Mark EI-3 as COMPLETE (✅) in `docs/EXTRACTION_IMPROVEMENT_PLAN.md` task table
   - Update status from 🟡 PENDING to ✅ COMPLETE with date

3. **Archive This Prompt**:
   - Move this file to `docs/archive/workstreams/EI-extraction-improvements/WORKER_PROMPT_TASK_EI-3.md`
   - Create the `EI-extraction-improvements` directory if it doesn't exist

4. **Commit and Push**:
   ```bash
   # Stage changes
   git add src/extraction/value_extractor.py \
           tests/unit/extraction/test_value_extractor.py \
           docs/EXTRACTION_IMPROVEMENT_PLAN.md \
           docs/completion/EI-3_COMPLETION_SUMMARY.md

   # Commit with descriptive message
   git commit -m "$(cat <<'EOF'
   EI-3: Integrate FalsePositiveFilter in ValueExtractor

   Add false positive filtering to all ValueExtractor extraction methods,
   applying the same proven filtering used by CandidateGenerator to prevent
   extraction of page numbers, years, TOC references, and date components.

   Changes:
   - Import FalsePositiveFilter and NumberMatch
   - Initialize filter in __init__
   - Add _is_false_positive_value() helper method
   - Apply filter in extract_from_text()
   - Apply filter in extract_from_table()
   - Apply filter in extract_from_text_with_llm()
   - Apply filter in extract_from_table_with_llm()
   - Graceful error handling when filter unavailable

   This unifies filtering between candidate generation and value extraction,
   eliminating the two-tier quality problem where candidates were filtered
   but extracted values contained false positives.

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"

   git push origin main
   ```

## Integration Notes (Post-EI-3)

After EI-3 is complete, EI-4 (TableRowParser validation) builds on this foundation:
- EI-4 adds row boundary validation using TableRowParser
- EI-4 depends on EI-3 being stable first
- Both filters work together: FalsePositiveFilter removes bad values, TableRowParser validates associations

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Problem 1 (Two-Tier Quality Architecture)
- **Dependencies**: None (first to use filter in ValueExtractor)
- **Enables**: EI-4 (TableRowParser Validation) - sequential dependency
- **Related tasks**:
  - EI-1 (Definition Filtering) - can run in parallel
  - EI-2 (Measurement Unit Patterns) - can run in parallel, patterns will be used by this filter
  - EI-4 (TableRowParser) - depends on this task
  - EI-6 (Integration Testing) - depends on this task
- **Proven pattern**: See `candidate_generator.py` for FalsePositiveFilter usage pattern

---

**Last Updated**: 2025-12-18
**Format Version**: 2.2 (concise requirements-focused format)

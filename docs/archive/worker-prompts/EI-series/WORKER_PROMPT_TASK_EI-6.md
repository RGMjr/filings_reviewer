# WORKER PROMPT: Task EI-6 - Integration Testing & Validation

```
===============================================================================
TASK ID:       EI-6
TASK NAME:     Integration testing and validation of all Phase 1 extraction fixes
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 - Final Validation
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-6_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 4-6 hours (test development 2-3 hours, execution & validation 2-3 hours)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Read-only validation, no production code changes
               - Risk: Tests may reveal incomplete fixes from EI-1 to EI-5
               - Impact: May require revisiting earlier tasks
               - Likelihood: Low (each task had unit tests)
               - Mitigation: Tests are diagnostic - identify issues early
TASK SIZE:     M (2-4 hours for core tests, up to 6 hours for full validation)
DEPENDS ON:    EI-1, EI-2, EI-3, EI-4, EI-5
UNLOCKS:       EI-7 (Re-extraction on All Filings)
BLOCKS:        EI-7
PARALLEL WITH: None (validation phase - sequential after all fixes)
===============================================================================
```

## Objective

Create comprehensive integration tests validating that all 5 Phase 1 extraction fixes (EI-1 through EI-5) work together correctly, eliminating the 4 critical bugs identified in the diagnostic analysis.

**Business Rationale**: Unit tests verify individual components work in isolation, but the extraction pipeline has complex interactions. Integration tests prove the end-to-end flow produces high-quality extractions on real SEC filings, giving confidence before re-extracting the entire database.

**Current Behavior**: No end-to-end tests validating the complete extraction pipeline with all EI-series filters applied together.

**Desired Behavior**: Integration test suite proves all 4 bugs are eliminated:
1. Definitions no longer generate candidates (EI-1)
2. Measurement units no longer extracted as values (EI-2)
3. Page numbers, years, TOC refs filtered (EI-3)
4. Cross-row table matches prevented (EI-4)
5. Cell boundaries preserved with markers (EI-5)

## Prerequisites

- EI-1 complete: Definition segments filtered in CandidateGenerator
- EI-2 complete: Measurement unit patterns added to FalsePositiveFilter
- EI-3 complete: FalsePositiveFilter integrated in ValueExtractor
- EI-4 complete: TableRowParser validation in ValueExtractor
- EI-5 complete: Cell boundary markers in HTMLSegmenter

**Verification**: Run these commands to confirm all prerequisites:
```bash
# Verify EI-1 through EI-4 completion summaries exist
ls docs/completion/EI-{1,2,3,4}_COMPLETION_SUMMARY.md

# Verify EI-5 completion summary exists
ls docs/completion/EI-5_COMPLETION_SUMMARY.md

# All unit tests pass
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ tests/unit/extraction/ --no-cov -q
```

## Files to Create

1. **`tests/integration/test_extraction_pipeline_fixes.py`** - Integration tests proving all EI-series fixes work together
2. **`scripts/validate_extraction_fixes.py`** - Validation script for manual testing on real filings (optional but recommended)

## Files to Read (Context Only)

- `tests/integration/test_e2_candidate_filtering.py` - Example integration test structure and fixtures
- `src/review/candidate_generator.py` - Understand how CandidateGenerator uses filters
- `src/extraction/value_extractor.py` - Understand how ValueExtractor extracts values
- `src/extraction/html_segmenter.py` - Understand how segments are created with markers
- `docs/completion/EI-{1,2,3,4}_COMPLETION_SUMMARY.md` - Understand what each fix implemented
- `docs/WORKER_PROMPT_TASK_EI-5.md` - Understand EI-5 marker format

## Implementation Requirements

### Core Functionality

1. **Integration Test Suite Structure**
   - Create `tests/integration/test_extraction_pipeline_fixes.py`
   - Use pytest fixtures for test database and sample data
   - Test real-world scenarios from actual S-1 filings
   - Each bug should have dedicated test(s) proving it's fixed

2. **Bug #1: Definitions as Metrics (EI-1 Validation)**
   - Create test segment with definition language: "We define daily active users (DAU) as users who engage with our platform in a 24-hour period"
   - Verify CandidateGenerator produces 0 candidates
   - Verify "24" from "24-hour period" is NOT extracted as a metric value
   - Test multiple definition patterns: "We define X as...", "X is defined as...", "X means..."

3. **Bug #2: Measurement Units (EI-2 Validation)**
   - Create test segments with: "24-hour period", "30-day retention", "7-day average", "12-month period"
   - Verify FalsePositiveFilter marks these numbers as false positives
   - Verify these numbers do NOT appear in extracted values
   - Test both hyphenated ("24-hour") and spaced ("24 hour") formats

4. **Bug #3: Page Numbers/Years/TOC (EI-3 Validation)**
   - Create test segment with page reference: "See page 23 for more details"
   - Create test segment with year: "In fiscal year 2019, we achieved..."
   - Create test segment with TOC pattern: "Risk Factors...................73"
   - Create test segment with date: "As of December 31, 2022..."
   - Verify none of these numbers appear in extracted values
   - Verify legitimate values in same segment ARE extracted

5. **Bug #4: Cross-Row Table Attribution (EI-4 Validation)**
   - Create table segment with HTML:
     ```html
     <table>
       <tr><td>Revenue</td><td>100,000</td></tr>
       <tr><td>Gross profit</td><td>262,431</td></tr>
       <tr><td>Cost</td><td>450,069</td></tr>
     </table>
     ```
   - Verify "Gross profit" matches "262,431" (same row), NOT "100,000" (prior row)
   - Verify TableRowParser correctly validates row boundaries
   - Test with various table structures (headers, merged cells)

6. **Bug #5: Cell Boundaries (EI-5 Validation)**
   - Create table segment and verify raw_text contains [CELL] and [ROW] markers
   - Verify "Retention Rate [CELL] 171% [CELL] 152%" format
   - Verify adjacent values are separated by markers
   - Verify position mapping still works with markers (numbers can be located)

7. **Combined Pipeline Tests**
   - Create segment with MULTIPLE issues (definition + measurement unit + page number)
   - Verify ALL filters applied correctly in combination
   - Verify no regression: legitimate values still extracted correctly
   - Test full extraction flow: HTMLSegmenter -> ValueExtractor -> CandidateGenerator

8. **Validation Script (Optional)**
   - Create `scripts/validate_extraction_fixes.py` for manual validation
   - Accept filing accession number as input
   - Run extraction pipeline with all fixes
   - Report counts: total values extracted, values filtered by each fix
   - Compare to expected ground truth if available

### Test Data Sources

**Use real-world patterns from known problematic filings**:
- Slack S-1: Known definition issues ("We define DAU as users active in a 24-hour period")
- Common table patterns from S-1 filings
- TOC structures from S-1 filings

**Test data fixtures should include**:
- Minimal HTML segments (fast tests)
- Representative S-1 segment samples
- Edge cases discovered during EI-1 to EI-5 implementation

### Error Handling

- **Missing prerequisite**: Test should skip with clear message (e.g., "@pytest.mark.skipif(not EI5_COMPLETE)")
- **Database errors**: Use transactional fixtures that rollback
- **Assertion failures**: Provide detailed diff showing expected vs actual

### Performance Requirements

- Integration test suite should complete in <60 seconds
- Individual tests should complete in <5 seconds
- Use database fixtures efficiently (share setup across tests)

## Test Requirements

### Coverage Target: **80%** for new test file (integration tests focus on scenarios, not line coverage)

### Test Categories (20+ tests recommended)

1. **Definition Filtering Tests** (4-5 tests)
   - `test_definition_segment_generates_zero_candidates` - "We define DAU as..." -> 0 candidates
   - `test_definition_with_number_in_period_not_extracted` - "24-hour period" -> 24 not extracted
   - `test_multiple_definition_patterns_filtered` - "defined as", "X means", "we define"
   - `test_non_definition_segment_still_generates_candidates` - Normal segment works
   - `test_partial_definition_language_handled` - Edge cases

2. **Measurement Unit Tests** (4-5 tests)
   - `test_hour_unit_filtered` - "24-hour" -> 24 filtered
   - `test_day_unit_filtered` - "30-day" -> 30 filtered
   - `test_spaced_unit_filtered` - "24 hour" (space not hyphen) -> filtered
   - `test_plural_units_filtered` - "days", "hours", "weeks" plural forms
   - `test_legitimate_number_near_unit_not_filtered` - "24,000 users per day" -> 24000 NOT filtered

3. **False Positive Filter Tests** (5-6 tests)
   - `test_page_number_filtered` - "page 23" -> 23 filtered
   - `test_year_filtered` - "2019" in date context -> filtered
   - `test_toc_reference_filtered` - "...........73" -> 73 filtered
   - `test_date_filtered` - "December 31, 2022" -> year filtered
   - `test_legitimate_value_same_segment_extracted` - "$50 million" extracted despite page number nearby
   - `test_combined_false_positives` - Multiple FP types in one segment

4. **Row Boundary Validation Tests** (4-5 tests)
   - `test_same_row_match_accepted` - Keyword and value in same row -> accepted
   - `test_cross_row_match_rejected` - Keyword row N, value row N-1 -> rejected
   - `test_header_row_not_matched_to_data` - Table headers don't match data values
   - `test_multi_column_table_correct_association` - Multiple columns match correctly
   - `test_irregular_table_handled` - Tables with missing cells, rowspan

5. **Cell Marker Tests** (3-4 tests)
   - `test_table_segment_has_cell_markers` - [CELL] present in raw_text
   - `test_table_segment_has_row_markers` - [ROW] present between rows
   - `test_numbers_still_findable_with_markers` - Can locate "171%" despite markers
   - `test_keyword_positions_correct_with_markers` - Position mapping works

6. **Combined Pipeline Tests** (3-4 tests)
   - `test_full_pipeline_no_false_positives` - All filters work together
   - `test_legitimate_values_still_extracted` - No regression in recall
   - `test_slack_s1_definition_scenario` - Specific known bug scenario
   - `test_complex_table_with_all_issues` - Table with definition, page number, etc.

### Known Edge Cases to Test

- Definition language in table cells (not just paragraphs)
- Measurement units as part of metric names ("30-day retention rate")
- Page numbers in footers vs body text
- Tables with mixed header/data rows
- Segments with no numbers at all (should produce 0 candidates)

## Acceptance Criteria

- [ ] Integration test file created: `tests/integration/test_extraction_pipeline_fixes.py`
- [ ] **20+ integration tests** covering all 5 bugs and combinations
- [ ] **Bug #1 verified**: Definition segments generate 0 candidates
- [ ] **Bug #2 verified**: Measurement units (N-hour, N-day, etc.) filtered
- [ ] **Bug #3 verified**: Page numbers, years, TOC refs, dates filtered
- [ ] **Bug #4 verified**: Cross-row table matches prevented
- [ ] **Bug #5 verified**: Cell markers present in table segment text
- [ ] **No regression**: Legitimate values still extracted (recall maintained)
- [ ] All 20+ integration tests pass
- [ ] Test suite completes in <60 seconds
- [ ] Validation script created (optional but recommended)
- [ ] All existing tests still pass (no regressions introduced)

## Do NOT

- Modify any source code in `src/` (this is validation only)
- Change existing tests (only add new integration tests)
- Skip tests if prerequisites not complete (mark as skip with clear message instead)
- Create tests that depend on external network resources
- Add new filter types or extraction logic (validation phase)
- Modify the database schema

## Verification Commands

```bash
# Run all new integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py -v

# Run specific bug category tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestDefinitionFiltering -v

TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestMeasurementUnits -v

TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestFalsePositiveFiltering -v

TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestRowBoundaryValidation -v

TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestCellMarkers -v

# Run combined/pipeline tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py::TestCombinedPipeline -v

# Verify no regression in existing tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/ tests/unit/ --no-cov -q

# Run validation script on sample filing (optional)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_extraction_fixes.py --accession-number "0001193125-19-104786"
```

## Expected Impact

**Before EI-1 to EI-5**:
- Definition segments generated false positive candidates
- "24" from "24-hour period" extracted as metric value
- Page numbers (23), years (2019), TOC refs (73) polluted data
- Cross-row matches created incorrect metric-value associations
- Adjacent table values merged together

**After EI-1 to EI-5 (validated by EI-6)**:
- 0 candidates from definition segments
- 0 measurement unit numbers extracted
- 0 page numbers, years, dates in extracted values
- 0 cross-row table matches
- Clear cell boundaries with [CELL] markers
- **>80% false positive reduction** (key metric)
- **No regression in recall** (legitimate values still extracted)

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example test structure</summary>

```python
"""
Integration tests for EI-1 through EI-5 extraction pipeline fixes.

Tests verify that all 5 bugs are eliminated when fixes work together.
"""
import pytest
from src.review.candidate_generator import CandidateGenerator
from src.extraction.value_extractor import ValueExtractor
from src.extraction.html_segmenter import HTMLSegmenter


class TestDefinitionFiltering:
    """EI-1: Verify definition segments generate 0 candidates."""

    @pytest.fixture
    def definition_segment(self, clean_db):
        """Create segment with definition language."""
        # Return segment dict with:
        # raw_text: "We define daily active users (DAU) as users active in a 24-hour period"
        # contains_definition_flag: True
        pass

    def test_definition_segment_generates_zero_candidates(self, clean_db, definition_segment):
        """Definition segment should produce no review candidates."""
        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(...)
        assert len(candidates) == 0, "Definition segment should not generate candidates"


class TestMeasurementUnits:
    """EI-2: Verify measurement unit numbers are filtered."""

    def test_hour_unit_filtered(self, clean_db):
        """24 from '24-hour period' should not be extracted."""
        # Create segment, run extraction, verify 24 not in results
        pass


class TestFalsePositiveFiltering:
    """EI-3: Verify page numbers, years, TOC refs filtered from extraction."""

    def test_page_number_filtered(self, clean_db):
        """Page numbers like 'page 23' should not be extracted."""
        pass


class TestRowBoundaryValidation:
    """EI-4: Verify cross-row table matches are prevented."""

    def test_same_row_match_accepted(self, clean_db):
        """Keyword and value in same table row should match."""
        pass

    def test_cross_row_match_rejected(self, clean_db):
        """Keyword in row N should not match value in row N-1."""
        pass


class TestCellMarkers:
    """EI-5: Verify cell boundary markers present in table segments."""

    def test_table_segment_has_cell_markers(self, clean_db):
        """Table segment raw_text should contain [CELL] markers."""
        pass


class TestCombinedPipeline:
    """Test all fixes working together end-to-end."""

    def test_full_pipeline_no_false_positives(self, clean_db):
        """Segment with multiple issues should have all false positives filtered."""
        # Create segment with: definition + page number + measurement unit
        # Run full pipeline
        # Verify only legitimate values extracted
        pass

    def test_legitimate_values_still_extracted(self, clean_db):
        """Filters should not prevent extraction of legitimate metric values."""
        # Create segment with: "We had $50 million in ARR"
        # Verify "$50 million" is extracted
        pass
```
</details>

## Post-Implementation Tasks

After completing EI-6:

1. **Create Completion Summary**:
   - Create `docs/completion/EI-6_COMPLETION_SUMMARY.md` with:
     - Summary of integration tests created
     - Test results (all passing)
     - False positive reduction metrics (if measured)
     - Any issues discovered and how resolved
     - Commit hash

2. **Update Documentation**:
   - Mark EI-6 as COMPLETE in `docs/EXTRACTION_IMPROVEMENT_PLAN.md` Progress Tracker
   - Update status from 🟡 PENDING to ✅ with date
   - Mark EI-7 as 🟡 READY (unblocked)

3. **Archive This Prompt**:
   - Move this file to `docs/archive/workstreams/EI-extraction-improvements/WORKER_PROMPT_TASK_EI-6.md`
   - Create the directory if it doesn't exist

4. **Commit and Push**:
   ```bash
   # Stage changes
   git add tests/integration/test_extraction_pipeline_fixes.py \
           scripts/validate_extraction_fixes.py \
           docs/EXTRACTION_IMPROVEMENT_PLAN.md \
           docs/completion/EI-6_COMPLETION_SUMMARY.md

   # Commit with descriptive message
   git commit -m "$(cat <<'EOF'
   EI-6: Add integration tests validating Phase 1 extraction fixes

   Create comprehensive integration test suite proving all 5 Phase 1
   extraction fixes (EI-1 through EI-5) work together correctly.

   Tests validate elimination of 4 critical bugs:
   - Bug #1: Definition segments no longer generate candidates
   - Bug #2: Measurement unit numbers (24-hour, 30-day) filtered
   - Bug #3: Page numbers, years, TOC refs, dates filtered
   - Bug #4: Cross-row table matches prevented
   - Bug #5: Cell boundaries preserved with [CELL]/[ROW] markers

   Integration test coverage:
   - 20+ tests across 6 test categories
   - Combined pipeline tests verify no regression in recall
   - Full test suite completes in <60 seconds

   This completes Phase 1 validation and unblocks EI-7 (re-extraction).

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"

   git push origin main
   ```

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 Final Validation
- **Dependencies**: EI-1, EI-2, EI-3, EI-4, EI-5 (all must be complete)
- **Enables**: EI-7 (Re-extraction on All Filings)
- **Related tasks**:
  - EI-1 (Definition Filtering) - verified by TestDefinitionFiltering
  - EI-2 (Measurement Units) - verified by TestMeasurementUnits
  - EI-3 (FalsePositiveFilter) - verified by TestFalsePositiveFiltering
  - EI-4 (TableRowParser) - verified by TestRowBoundaryValidation
  - EI-5 (Cell Markers) - verified by TestCellMarkers
- **Reference integration test**: `tests/integration/test_e2_candidate_filtering.py` (similar structure)

---

**Last Updated**: 2025-12-18
**Format Version**: 2.3 (concise requirements-focused format with dependency tracking)

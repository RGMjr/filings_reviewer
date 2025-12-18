# EXTRACTION Improvement Plan: Unified Extraction Architecture

**Created**: 2025-12-17
**Status**: Planning
**Workstream**: Extraction & Candidate Identification Quality
**Prerequisites**: None (standalone workstream)

---

## Executive Summary

Critical quality failures identified in extraction and candidate identification logic:

| Issue | Impact | Evidence |
|-------|--------|----------|
| **Definitions as metrics** | Critical | "We define DAU as..." extracted as metric, "24" from "24-hour period" as value |
| **Prior row attribution** | Critical | Metric labels from table row N matched to values in row N-1 |
| **Page numbers as values** | Critical | Page numbers, TOC references, years extracted as metric values |
| **Adjacent values in text** | Critical | "Retention Rate171% 152% 143%" - cell boundaries lost |

**Root Cause**: CandidateGenerator has sophisticated filters (`TableRowParser`, `FalsePositiveFilter`, definition detection) but ValueExtractor doesn't use them. Two separate pipelines evolved independently, creating a **two-tier quality system**.

**Solution**: Phased hybrid approach - immediate incremental fixes (Phase 1: ~20 hours) followed by optional selective architectural improvements (Phase 2: ~12 hours).

---

## Diagnostic Findings

### Problem 1: Two-Tier Quality Architecture

**CandidateGenerator** (`src/review/`):
- ✅ Table row-aware matching (`TableRowParser`)
- ✅ False positive filtering (page numbers, years, dates)
- ✅ Definition language detection
- ✅ Sentence boundary awareness
- ✅ Comprehensive configuration system

**ValueExtractor** (`src/extraction/`):
- ❌ No row boundary validation
- ❌ No false positive filtering
- ❌ No definition exclusion
- ❌ Processes all numbers indiscriminately

**Result**: Candidates are filtered but extracted values contain the same false positives that candidates exclude.

### Problem 2: Incomplete Integration of Existing Infrastructure

**Already exists but underutilized**:
- `src/review/table_structure.py` (277 lines) - `TableRowParser` with `are_in_same_row()` method
- `src/review/false_positive_filter.py` - Comprehensive TOC, page, date filtering
- `src/web/table_html_extractor.py` (159 lines) - Table HTML extraction
- `src/review/boundary_detection.py` - Sentence boundary detection

**Integration status**:
- ✅ Used in: `CandidateGenerator`
- ❌ Missing from: `ValueExtractor`, `HTMLSegmenter` (for tables)

### Problem 3: Text Normalization Destroys Structure

**Current flow**:
```
HTML: <tr><td>Gross profit</td><td>262,431</td></tr>
      <tr><td>Cost</td><td>450,069</td></tr>

After normalization: "Gross profit 262,431 Cost 450,069"
```

**Issue**: Cell boundaries lost → keywords can match wrong row's numbers

**Location**: `src/extraction/html_segmenter.py:1027-1041` (`_normalize_text()`)

### Problem 4: Definition Language Treated as Positive Signal

**Current behavior**: `src/review/confidence_scoring.py:291-293`
```python
if features.contains_definition_language:
    score += self.DEFINITION_BONUS  # +0.20
```

**Should be**: Filter out or penalize definition segments

**Pattern detection works**: `src/review/feature_extractor.py:131-141` detects "we define", "defined as", etc.

**But wrong conclusion**: Definition language INCREASES confidence instead of excluding

---

## Task Breakdown for Orchestrator/Architect

### Phase 1: Incremental Fixes (Immediate Priority)

All 5 fixes integrate existing proven components with minimal architectural changes.

| Task ID | Name | Prerequisites | Time Est | Risk | Status |
|---------|------|---------------|----------|------|--------|
| **EI-1** | Filter Definition Segments | None | 1 hour | Low | ✅ COMPLETE (2025-12-18) |
| **EI-2** | Add Measurement Unit Patterns | None | 1-2 hours | Low | ✅ COMPLETE (2025-12-18) |
| **EI-3** | Integrate FalsePositiveFilter in ValueExtractor | None | 3-4 hours | Low | ✅ COMPLETE (2025-12-18) |
| **EI-4** | Add TableRowParser Validation to ValueExtractor | EI-3 | 4-5 hours | Medium | 🟡 PENDING |
| **EI-5** | Add Cell Boundary Markers to HTMLSegmenter | None | 6-8 hours | Medium | 🟡 PENDING |
| **EI-6** | Integration Testing & Validation | EI-1 to EI-5 | 4-6 hours | Low | 🟡 PENDING |
| **EI-7** | Re-extraction on All Filings | EI-6 | 2-4 hours | Low | 🟡 PENDING |

**Total Phase 1 Time**: 21-31 hours (3-4 days)

### Phase 2: Optional Architectural Enhancements (If Needed)

Only pursue if Phase 1 reveals persistent quality issues.

| Task ID | Name | Prerequisites | Time Est | Risk | Status |
|---------|------|---------------|----------|------|--------|
| **EA-1** | Create StructureParser Module | EI-7 complete | 4-6 hours | Low | 🟡 PENDING |
| **EA-2** | Create Unified CandidateDetector | EA-1 | 6-8 hours | Medium | 🟡 PENDING |
| **EA-3** | Implement Table-Aware Context Extraction | EA-1 | 3-4 hours | Low | 🟡 PENDING |

**Total Phase 2 Time**: 13-18 hours (optional)

---

## Detailed Task Specifications: Phase 1

### EI-1: Filter Definition Segments

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-1
TASK NAME:     Filter out definition segments from candidate generation
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-1_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 1 hour (implementation 30 min, testing 30 min)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Simple filter, no architectural changes
PARALLEL WITH: EI-2, EI-3
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Prevent segments containing definition language ("We define X as...", "X is defined as...") from generating review candidates.

**Business Rationale**: Definitions explain what metrics mean but don't disclose actual values. Currently "We define daily active users as users active in a 24-hour period" generates a candidate with value "24", wasting reviewer time.

**Current Behavior**: Definition segments generate candidates. The `contains_definition_flag` is detected but ignored during candidate generation.

**Desired Behavior**: Segments with `contains_definition_flag=True` generate zero candidates.

#### Prerequisites

- None (standalone fix)

#### Files to Modify

1. **`src/review/candidate_generator.py`** - Add definition filter in `_process_segment()` method (around line 590)

#### Files to Read (Context Only)

- `src/review/feature_extractor.py` - Understand how `contains_definition_flag` is set (lines 131-141, 359-372)
- `src/extraction/models.py` - Understand `SourceSegment` structure

#### Implementation Requirements

### Core Functionality

1. **Definition Filter**
   - Check if `segment.get("contains_definition_flag")` is `True` before creating candidates
   - Skip candidate generation for definition segments
   - Log skip reason for debugging

2. **Location**: In `_process_segment()` method after keyword matching but before creating candidate
   ```python
   # After finding keyword_matches (around line 590)
   if segment.get("contains_definition_flag"):
       logger.debug(f"Skipping candidate in definition segment")
       continue
   ```

### Error Handling

- **Missing flag**: If `contains_definition_flag` not present, default to `False` (don't filter)
- **No exceptions**: Use `.get()` to avoid KeyError

### Test Requirements

#### Coverage Target: **Maintain ≥90%** for `src/review/candidate_generator.py`

#### Test Categories (3-5 tests recommended)

1. **Definition Filtering** (3-4 tests)
   - Definition segment with "We define X as..." generates 0 candidates
   - Definition segment with "X is defined as..." generates 0 candidates
   - Non-definition segment with number generates candidates normally
   - Segment without `contains_definition_flag` generates candidates normally

#### Acceptance Criteria

- [ ] Definition segments (`contains_definition_flag=True`) generate 0 candidates
- [ ] Non-definition segments generate candidates normally
- [ ] 3+ unit tests covering definition and non-definition cases
- [ ] All existing tests still pass
- [ ] NO changes to `feature_extractor.py` or other modules

#### Do NOT

- Modify `feature_extractor.py` (definition detection logic is correct)
- Change definition patterns (they're working correctly)
- Add new configuration parameters (simple if-statement is sufficient)

#### Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py::test_definition_filtering -v

# Verify no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py --no-cov -q
```

#### Expected Impact

**Before EI-1**:
- Slack filing generates candidate from "active in a 24-hour period" with value "24"
- Definition segments waste reviewer time

**After EI-1**:
- Definition segments generate 0 candidates
- Only actual metric disclosures reviewed

---

### EI-2: Add Measurement Unit Patterns

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-2
TASK NAME:     Add measurement unit patterns to false positive filter
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-2_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 1-2 hours (implementation 30 min, testing 60 min)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Adding patterns to existing filter
PARALLEL WITH: EI-1, EI-3
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Filter out numbers that are part of measurement units (e.g., "24" in "24-hour period", "30" in "30-day window") to prevent them from being identified as metric values.

**Business Rationale**: Numbers in measurement units are part of metric definitions, not values. "24-hour period" describes the measurement timeframe, not a quantity.

**Current Behavior**: "24-hour period", "30-day window", "7-day average" not filtered. These numbers get extracted as candidate values.

**Desired Behavior**: Numbers immediately followed by time unit words (hour, day, week, month, year) are filtered as false positives.

#### Prerequisites

- None (standalone enhancement)

#### Files to Modify

1. **`src/review/false_positive_filter.py`** - Add patterns to `FALSE_POSITIVE_CONTEXT_PATTERNS` (around line 156)

#### Files to Read (Context Only)

- `src/review/false_positive_filter.py` - Understand existing pattern structure (lines 109-182)

#### Implementation Requirements

### Core Functionality

1. **Measurement Unit Patterns**
   - Add regex patterns to detect numbers followed by time units
   - Support hyphenated ("24-hour") and spaced ("24 hour") formats
   - Support singular and plural ("day" and "days")
   - Include common time units: hour, day, week, month, year, minute, second, period

2. **Pattern Examples**
   ```python
   # After existing FALSE_POSITIVE_CONTEXT_PATTERNS (around line 156)
   # Measurement unit patterns - numbers within units are not metrics
   re.compile(r"\b\d+[-\s](?:hour|day|week|month|year|period)(?:s)?\b", re.IGNORECASE),
   re.compile(r"\b\d+[-\s](?:minute|second)(?:s)?\b", re.IGNORECASE),
   ```

### Error Handling

- **Pattern compilation**: Patterns should compile without errors
- **Case insensitivity**: Use `re.IGNORECASE` flag

### Test Requirements

#### Coverage Target: **Maintain ≥90%** for `src/review/false_positive_filter.py`

#### Test Categories (5-8 tests recommended)

1. **Measurement Unit Detection** (6-8 tests)
   - "24-hour period" filters 24
   - "24 hour period" filters 24 (space instead of hyphen)
   - "30-day window" filters 30
   - "7-day average" filters 7
   - "12-month period" filters 12
   - "90-second interval" filters 90
   - "5-year plan" filters 5
   - Numbers NOT followed by units pass through (e.g., "24,000 customers")

#### Acceptance Criteria

- [ ] Numbers in "N-hour", "N-day", "N-week", "N-month", "N-year" patterns filtered
- [ ] Hyphenated and spaced formats both work
- [ ] Singular and plural forms both work
- [ ] 6+ unit tests covering various time units
- [ ] All existing tests still pass
- [ ] NO impact on legitimate metric values

#### Do NOT

- Remove existing patterns (additive change only)
- Change filter logic (just add patterns)
- Add patterns for non-time units (scope: time units only)

#### Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py::test_measurement_units -v

# Verify coverage maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py \
  --cov=src/review/false_positive_filter --cov-report=term-missing -q
```

#### Expected Impact

**Before EI-2**:
- "24" from "24-hour period" extracted as candidate value
- "30" from "30-day retention" extracted as candidate value

**After EI-2**:
- Measurement unit numbers filtered out
- Only actual metric values pass through

---

### EI-3: Integrate FalsePositiveFilter in ValueExtractor

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-3
TASK NAME:     Integrate FalsePositiveFilter into ValueExtractor extraction methods
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-3_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 3-4 hours (implementation 90 min, testing 90-120 min)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Reusing proven component from CandidateGenerator
PARALLEL WITH: EI-1, EI-2
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Apply the same false positive filtering used in CandidateGenerator to ValueExtractor, preventing page numbers, years, TOC references, and dates from being extracted as metric values.

**Business Rationale**: ValueExtractor currently extracts all numbers without filtering, including page numbers (e.g., "page 23"), years (e.g., "2019"), and TOC references. These pollute the extracted data and waste analyst time.

**Current Behavior**: ValueExtractor extracts page numbers, years, dates, TOC references as metric values.

**Desired Behavior**: ValueExtractor applies FalsePositiveFilter before extraction, same as CandidateGenerator.

#### Prerequisites

- None (FalsePositiveFilter already exists and is proven)

#### Files to Modify

1. **`src/extraction/value_extractor.py`** - Import and integrate FalsePositiveFilter in all extraction methods

#### Files to Read (Context Only)

- `src/review/false_positive_filter.py` - Understand FalsePositiveFilter API (lines 381-466 show `is_false_positive()`)
- `src/review/number_parsing.py` - Understand NumberMatch structure
- `src/review/candidate_generator.py` - See how it uses FalsePositiveFilter (lines 587-593)

#### Implementation Requirements

### Core Functionality

1. **Import and Initialize Filter**
   - Import `FalsePositiveFilter` and `NumberMatch` at top of file (around line 15)
   - Initialize `self._fp_filter = FalsePositiveFilter()` in `__init__` (around line 283)

2. **Apply Filter in All Extraction Methods**
   - `extract_from_text()` (line ~428): Filter numbers before creating MetricValue
   - `extract_from_table()` (line ~353): Filter numbers before creating MetricValue
   - `extract_from_text_with_llm()` (line ~458): Filter numbers from LLM results
   - `extract_from_table_with_llm()` (line ~614): Filter numbers from LLM results

3. **Filter Application Pattern**
   ```python
   # Before using a number, create NumberMatch and check filter
   num_match = NumberMatch(
       start=num_pos,
       end=num_pos + len(value_str),
       raw_text=value_str,
       value=Decimal(str(numeric_value)),
       unit=unit
   )
   is_fp, reason = self._fp_filter.is_false_positive(segment.raw_text, num_match)
   if is_fp:
       logger.debug(f"Filtered false positive: {value_str} (reason: {reason})")
       continue  # Skip this value
   ```

### Error Handling

- **Filter errors**: If filter raises exception, log warning and continue (don't filter)
- **Missing position**: If can't find number position in text, log warning but don't filter

### Performance Requirements

- Filter check adds ~1-2ms per number (negligible for typical segments)
- No significant performance impact expected

### Test Requirements

#### Coverage Target: **Maintain ≥85%** for `src/extraction/value_extractor.py`

#### Test Categories (12-15 tests recommended)

1. **False Positive Filtering** (8-10 tests)
   - Page numbers filtered ("page 23", "p. 45")
   - Years filtered (1990-2100)
   - TOC proximity filtered
   - TOC page references filtered (dot leaders)
   - Dates filtered ("January 31, 2019", "as of...")
   - Legitimate numbers pass through (24,000 customers)
   - Filter applied in `extract_from_text()`
   - Filter applied in `extract_from_table()`
   - Filter applied in LLM extraction methods

2. **Error Handling** (2-3 tests)
   - Missing position in text handled gracefully
   - Filter exception doesn't break extraction

#### Acceptance Criteria

- [ ] FalsePositiveFilter imported and initialized in `__init__`
- [ ] Filter applied in all 4 extraction methods
- [ ] Page numbers excluded from extraction
- [ ] Years (1990-2100) excluded from extraction
- [ ] TOC references excluded from extraction
- [ ] Dates excluded from extraction
- [ ] Legitimate metric values still extracted
- [ ] 12+ unit tests covering all filter types
- [ ] Coverage maintained ≥85%
- [ ] All existing tests still pass
- [ ] NO changes to FalsePositiveFilter itself

#### Do NOT

- Modify `false_positive_filter.py` (reuse as-is)
- Add new filter types (use existing filter)
- Change extraction logic beyond adding filter (minimal changes)
- Break existing LLM extraction functionality

#### Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py::test_false_positive_filtering -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py \
  --cov=src/extraction/value_extractor --cov-report=term-missing -q

# Verify no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q
```

#### Expected Impact

**Before EI-3**:
- "Page 23" extracted as metric value 23
- Year "2019" extracted as metric value
- TOC ".....................73" extracted as 73

**After EI-3**:
- Page numbers, years, TOC refs filtered out
- Only legitimate metric values extracted
- ~80% reduction in false positive extractions

---

### EI-4: Add TableRowParser Validation to ValueExtractor

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-4
TASK NAME:     Add TableRowParser validation to prevent cross-row keyword-value matching
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-4_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 4-5 hours (implementation 2-2.5 hours, testing 2-2.5 hours)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Medium - Modifies table extraction logic, must preserve existing functionality
PARALLEL WITH: None (sequential after EI-3)
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Use TableRowParser in ValueExtractor to validate that keyword-value pairs are in the same table row, preventing "Gross profit" in row N from being matched to values in row N-1.

**Business Rationale**: Table extraction currently assumes cell indices map correctly to values, but this fails when row structure is irregular. Validating same-row constraint ensures accurate metric-value associations.

**Current Behavior**: Keywords from row N can match values from row N-1 or N+1. Example: "Gross profit" label matches "Cost of revenues" value from prior row.

**Desired Behavior**: Keyword-value pairs validated to be in same row. Cross-row matches rejected with warning.

#### Prerequisites

- EI-3 complete (false positive filter integration verified working)

#### Files to Modify

1. **`src/extraction/value_extractor.py`** - Add TableRowParser to `extract_from_table()` and `_parse_table_row()` methods

#### Files to Read (Context Only)

- `src/review/table_structure.py` - Understand TableRowParser API (lines 217-238 show `are_in_same_row()`)
- `src/review/candidate_generator.py` - See how it uses TableRowParser (lines 568-578, 595-596)
- `src/review/keyword_matching.py` - See row filtering logic (lines 502-525)

#### Implementation Requirements

### Core Functionality

1. **Import and Initialize TableRowParser**
   - Import `TableRowParser` at top of file (around line 15)
   - In `extract_from_table()` method, create TableRowParser from `segment.raw_html` and `segment.raw_text`

2. **Pass TableRowParser to Row Parsing**
   - Modify `_parse_table_row()` signature to accept `row_parser` parameter
   - Pass `row_parser` when calling `_parse_table_row()`

3. **Validate Row Boundaries**
   - Find text position of cohort label in `segment.raw_text`
   - Find text position of value in `segment.raw_text`
   - Use `row_parser.are_in_same_row(cohort_pos, value_pos)` to validate
   - If not in same row, log warning and skip value

4. **Fallback Handling**
   - If `TableRowParser` initialization fails, proceed without validation (don't break extraction)
   - If position not found in text, proceed without validation
   - Log warnings for debugging but don't raise exceptions

### Error Handling

- **Missing raw_html**: Skip row parsing if no HTML available
- **Position not found**: Log warning, proceed without validation
- **Parser initialization fails**: Log warning, proceed without validation
- **No exceptions should propagate**: Extraction should complete even if validation fails

### Performance Requirements

- TableRowParser creation adds ~10-50ms per table segment
- Position lookups add ~1-2ms per cell
- Acceptable overhead for accuracy improvement

### Test Requirements

#### Coverage Target: **Maintain ≥85%** for `src/extraction/value_extractor.py`

#### Test Categories (10-12 tests recommended)

1. **Row Boundary Validation** (6-8 tests)
   - Keywords from row N don't match values from row N+1
   - Keywords from row N don't match values from row N-1
   - Keywords and values in same row match correctly
   - Row heading in first cell matches values in same row
   - Multi-row table with headers in each row
   - Table without row headers handled

2. **Edge Cases** (4-5 tests)
   - Segment without raw_html handled gracefully
   - Position not found in text handled gracefully
   - TableRowParser initialization failure handled
   - Table with irregular structure (rowspan/colspan)
   - Empty rows ignored

#### Known Edge Cases to Test

- Tables with merged cells (colspan/rowspan)
- Tables with missing cells
- Inconsistent row lengths
- Text normalization mismatches between HTML and text

#### Acceptance Criteria

- [ ] TableRowParser imported and initialized for table segments
- [ ] `_parse_table_row()` accepts `row_parser` parameter
- [ ] Row boundary validation applied before creating MetricValue
- [ ] Cross-row matches logged and skipped
- [ ] Same-row matches proceed normally
- [ ] Fallback handling when parser unavailable
- [ ] 10+ unit tests covering validation and edge cases
- [ ] Coverage maintained ≥85%
- [ ] All existing tests still pass
- [ ] NO changes to TableRowParser itself

#### Do NOT

- Modify `table_structure.py` (reuse as-is)
- Change table parsing HTML logic (only add validation)
- Break existing table extraction for non-table segments
- Raise exceptions that break extraction

#### Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py::test_row_boundary_validation -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py \
  --cov=src/extraction/value_extractor --cov-report=term-missing -q

# Verify no regressions in table extraction
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_value_extractor.py::test_extract_from_table -v
```

#### Expected Impact

**Before EI-4**:
- "Gross profit" label matches "450,069" from "Cost of revenues" row
- Cross-row attribution creates false associations

**After EI-4**:
- Cross-row matches detected and rejected
- Only same-row keyword-value pairs accepted
- ~95% accuracy in table row associations

---

### EI-5: Add Cell Boundary Markers to HTMLSegmenter

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-5
TASK NAME:     Add cell boundary markers to preserve table structure in text extraction
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-5_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 6-8 hours (implementation 3-4 hours, testing 3-4 hours)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Medium - Changes text extraction format, must verify position mapping still works
PARALLEL WITH: None (can run parallel with EI-3/EI-4 but coordination needed)
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Preserve table cell boundaries in extracted text by adding `[CELL]` and `[ROW]` markers during HTML-to-text conversion, preventing "Retention Rate171% 152% 143%" type issues.

**Business Rationale**: When table cells are collapsed to text, adjacent numbers merge together, making it unclear which number belongs to which metric. Cell markers preserve structure without requiring DOM parsing downstream.

**Current Behavior**: Table HTML like `<td>Revenue</td><td>100</td><td>200</td>` becomes "Revenue 100 200" (ambiguous).

**Desired Behavior**: Same table becomes "Revenue [CELL] 100 [CELL] 200" with clear cell boundaries.

#### Prerequisites

- None (can run independently, but test integration with EI-3/EI-4 if available)

#### Files to Modify

1. **`src/extraction/html_segmenter.py`** - Add `_extract_table_text_with_markers()` method and modify `_extract_segment()` to use it

#### Files to Read (Context Only)

- `src/extraction/html_segmenter.py` - Understand current `_normalize_text()` and `_extract_segment()` (lines 1027-1041, ~728)
- `src/review/table_structure.py` - Understand how TableRowParser expects text format

#### Implementation Requirements

### Core Functionality

1. **Create _extract_table_text_with_markers() Method**
   - Extract table rows using BeautifulSoup `find_all('tr')`
   - For each row, extract cell text from `find_all(['td', 'th'])`
   - Join cells with ` [CELL] ` separator
   - Join rows with ` [ROW] ` separator
   - Apply `_normalize_text()` to individual cells before joining

2. **Modify _extract_segment() for Tables**
   - Detect if `element.name == "table"`
   - Use `_extract_table_text_with_markers()` instead of `_normalize_text(element.get_text())`
   - Preserve existing behavior for non-table elements

3. **Marker Format**
   - Cell separator: ` [CELL] ` (space-bracket-CELL-bracket-space)
   - Row separator: ` [ROW] ` (space-bracket-ROW-bracket-space)
   - Markers are part of segment text (positions include them)

### Error Handling

- **Empty cells**: Skip empty cells, don't add markers for them
- **Nested tables**: Apply markers to innermost table only (BeautifulSoup default behavior)
- **Malformed HTML**: If table parsing fails, fall back to standard `_normalize_text()`

### Performance Requirements

- Marker insertion adds ~5-20ms per table segment
- Negligible overhead for non-table segments (no change)

### Test Requirements

#### Coverage Target: **Maintain ≥90%** for `src/extraction/html_segmenter.py`

#### Test Categories (15-20 tests recommended)

1. **Cell Marker Insertion** (8-10 tests)
   - Single row table has [CELL] markers
   - Multi-row table has [ROW] markers
   - Marker positions tracked correctly
   - Empty cells skipped
   - Headers (th) and data (td) both get markers
   - Adjacent values separated by [CELL]
   - Cell text normalized before marker insertion

2. **Position Mapping** (4-5 tests)
   - Character positions after markers still map to HTML correctly
   - TableRowParser works with marker text
   - KeywordMatching works with marker text
   - NumberParsing works with marker text

3. **Edge Cases** (3-5 tests)
   - Table with rowspan/colspan
   - Nested tables
   - Table with only headers (no data rows)
   - Very large table (100+ cells)

#### Known Edge Cases to Test

- Tables extracted from composite segments
- Tables with mixed content (text + images in cells)
- Tables with whitespace-only cells

#### Acceptance Criteria

- [ ] `_extract_table_text_with_markers()` method created
- [ ] Table elements use marker-based extraction
- [ ] Non-table elements unchanged (use existing `_normalize_text()`)
- [ ] [CELL] markers separate adjacent cell values
- [ ] [ROW] markers separate table rows
- [ ] Empty cells skipped (no markers for empty content)
- [ ] TableRowParser compatible with marker text
- [ ] 15+ unit tests covering markers and edge cases
- [ ] Coverage maintained ≥90%
- [ ] All existing tests still pass
- [ ] **Integration verified**: Run with EI-4 to ensure row parsing works

#### Do NOT

- Change marker format after testing starts (downstream dependencies)
- Add markers to non-table elements (scope: tables only)
- Break existing segment text positions for non-tables
- Remove `_normalize_text()` (still needed for cells and non-tables)

#### Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py::test_table_markers -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  --cov=src/extraction/html_segmenter --cov-report=term-missing -q

# Verify TableRowParser compatibility (if EI-4 available)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_table_structure.py -v

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q
```

#### Expected Impact

**Before EI-5**:
- Table text: "Retention Rate171% 152% 143%" (ambiguous)
- Cell boundaries lost
- Adjacent numbers merge

**After EI-5**:
- Table text: "Retention Rate [CELL] 171% [CELL] 152% [CELL] 143%"
- Cell boundaries preserved
- Clear separation of values

---

### EI-6: Integration Testing & Validation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-6
TASK NAME:     Integration testing and validation of all Phase 1 fixes
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-6_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 4-6 hours (test development 2-3 hours, execution & validation 2-3 hours)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Read-only validation, no code changes
PARALLEL WITH: None (sequential after EI-1 to EI-5)
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Validate that all 5 Phase 1 fixes work together correctly and eliminate the reported bugs through integration tests on real S-1 filings.

**Business Rationale**: Unit tests verify individual components, but integration tests prove the end-to-end extraction pipeline works correctly on actual SEC filings.

**Current Behavior**: No end-to-end tests for complete extraction pipeline with all filters.

**Desired Behavior**: Integration tests prove all 4 bugs eliminated on Slack S-1 and other test filings.

#### Prerequisites

- EI-1 complete (definition filtering)
- EI-2 complete (measurement units)
- EI-3 complete (false positive filter)
- EI-4 complete (row validation)
- EI-5 complete (cell markers)

#### Files to Create

1. **`tests/integration/test_extraction_pipeline_fixes.py`** - Integration tests for EI-1 to EI-5 fixes
2. **`scripts/validate_extraction_fixes.py`** - Validation script for manual testing

#### Files to Read (Context Only)

- `tests/integration/test_e2_candidate_filtering.py` - Example integration test structure
- Slack S-1 filing (known bug examples)

#### Implementation Requirements

### Core Functionality

1. **Integration Test Suite**
   - Test full extraction pipeline on real S-1 segments
   - Verify all 4 bugs eliminated:
     - Definitions don't generate candidates
     - Cross-row matches prevented
     - Page numbers filtered
     - Cell boundaries preserved

2. **Test Data**
   - Use Slack S-1 filing segments (known bug examples)
   - Include segments with:
     - Definition language ("We define DAU as...")
     - Multi-row tables
     - Page number context
     - Adjacent table cells

3. **Validation Script**
   - Run extraction on 5-10 test filings
   - Count false positives by category
   - Report before/after metrics
   - Generate validation report

### Test Requirements

#### Coverage Target: **≥80%** for new integration test file

#### Test Categories (10-15 tests recommended)

1. **Bug Elimination Tests** (8-10 tests)
   - Definition segment generates 0 candidates (Bug #1 fixed)
   - Measurement units filtered (EI-2 verified)
   - Page numbers filtered in extraction (Bug #3 fixed)
   - Cross-row table matches prevented (Bug #2 fixed)
   - Cell markers preserve boundaries (Bug #4 fixed)
   - All filters work together

2. **No Regression Tests** (4-5 tests)
   - Legitimate candidates still generated
   - Legitimate values still extracted
   - Non-table segments unchanged
   - LLM extraction still works

#### Acceptance Criteria

- [ ] Integration test file created with 10+ tests
- [ ] All 4 bugs verified eliminated on Slack S-1
- [ ] Validation script runs on 5-10 filings
- [ ] False positive reduction measured and documented
- [ ] No regression in recall (compared to baseline)
- [ ] All integration tests pass
- [ ] Validation report shows >80% false positive reduction

#### Do NOT

- Make code changes (validation only)
- Add new functionality (testing phase)
- Modify test filings

#### Verification Commands

```bash
# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_extraction_pipeline_fixes.py -v

# Run validation script
python3 scripts/validate_extraction_fixes.py

# Full regression suite
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/ --no-cov -q
```

#### Expected Impact

**Before EI-1 to EI-5**:
- 4 critical bugs present
- High false positive rate

**After EI-1 to EI-5**:
- 0 definition candidates
- 0 cross-row matches
- 0 page number extractions
- Cell boundaries preserved
- >80% false positive reduction
- No recall regression

---

### EI-7: Re-extraction on All Filings

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-7
TASK NAME:     Re-run extraction on all filings with Phase 1 fixes
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-7_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 2-4 hours (script development 1 hour, execution & monitoring 1-3 hours)
TIME ACTUAL:   [TBD]
RISK LEVEL:    Low - Read-only extraction, staged rollout
PARALLEL WITH: None (sequential after EI-6)
═══════════════════════════════════════════════════════════════════════════════
```

#### Objective

Re-extract all filings using the improved extraction pipeline to populate database with higher-quality data.

**Business Rationale**: Existing extracted values contain false positives. Re-extraction with fixes provides clean data for analysis.

**Current Behavior**: Database contains values extracted with bugs (page numbers, definitions, cross-row matches).

**Desired Behavior**: Database contains only high-quality extracted values with bugs eliminated.

#### Prerequisites

- EI-6 complete (integration tests pass)
- Validation shows >80% false positive reduction
- No regressions detected

#### Files to Create

1. **`scripts/reextract_all_filings.py`** - Re-extraction script with progress monitoring

#### Files to Modify

1. **`CLAUDE.md`** - Document re-extraction date and quality improvements

#### Implementation Requirements

### Core Functionality

1. **Re-extraction Script**
   - Fetch all filing IDs from database
   - For each filing:
     - Delete existing extracted values
     - Re-run extraction with EI-1 to EI-5 fixes
     - Store new values
     - Track progress and errors

2. **Progress Monitoring**
   - Log extraction progress (filings processed, values extracted)
   - Estimate time remaining
   - Report errors but continue processing

3. **Validation**
   - Compare before/after value counts
   - Measure false positive reduction
   - Verify no total loss of data (recall check)

### Error Handling

- **Extraction failures**: Log error, continue to next filing
- **Database errors**: Retry once, then skip and log
- **Resume capability**: Support resuming from last successful filing

### Performance Requirements

- Process full database in <8 hours
- Batch updates for efficiency
- Commit every N filings for progress persistence

### Acceptance Criteria

- [ ] Re-extraction script created
- [ ] Progress monitoring implemented
- [ ] Error handling and resume capability
- [ ] Re-extraction completes successfully
- [ ] Before/after metrics documented
- [ ] False positive reduction verified
- [ ] No significant recall regression
- [ ] CLAUDE.md updated with results

#### Do NOT

- Run on production database without testing on staging first
- Delete extracted values without backup
- Skip error logging

#### Verification Commands

```bash
# Test on staging database first
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py --dry-run

# Run on staging database
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/reextract_all_filings.py

# Compare metrics
python3 scripts/compare_extraction_metrics.py
```

#### Expected Impact

**Before EI-7**:
- Database contains false positives
- Page numbers, definitions, cross-row matches in data

**After EI-7**:
- Clean database with bugs eliminated
- >80% false positive reduction
- Improved data quality for analysis

---

## Phase 2: Optional Architectural Enhancements

*Only pursue if Phase 1 reveals persistent quality issues or if clean-sheet architecture is desired for long-term maintainability.*

Tasks EA-1, EA-2, EA-3 would create:
- `StructureParser` module for DOM tree preservation
- Unified `CandidateDetector` for both extraction and review
- Table-aware context extraction

See agent reports for detailed specifications of Phase 2 tasks.

---

## Success Metrics

### Must Achieve (Phase 1)

- [ ] 0 candidates from definition segments
- [ ] 0 cross-row keyword-value matches in tables
- [ ] 0 page numbers/years/dates in extracted values
- [ ] Cell boundaries preserved in all table segments
- [ ] >80% false positive reduction measured
- [ ] No regression in recall (≥ baseline)
- [ ] All existing tests pass
- [ ] New tests have ≥90% coverage

### Should Achieve (Quality Targets)

- [ ] Precision improved by >15 percentage points
- [ ] Re-extraction completes in <8 hours
- [ ] Manual validation of 20 candidates shows 0 bugs
- [ ] Integration tests prove end-to-end correctness

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Cell markers break position mapping | Medium | High | EI-5 includes position mapping tests, integration with TableRowParser |
| Row validation too strict | Low | Medium | Fallback allows match if position mapping fails |
| Re-extraction takes too long | Low | Low | Batch processing, progress monitoring, resume capability |
| Recall regression | Low | High | A/B test on sample before full rollout, extensive validation in EI-6 |

---

## Workflow Improvements Suggested

### Recommended Addition to instructions_orchestrator.md

Add after "Task Selection Strategy" section (line 45):

```markdown
6. **Consider System-Wide Impact**: For architecture changes affecting multiple modules:
   - Phase foundational changes first (data structures, shared utilities)
   - Enable parallel work on independent modules where possible
   - Plan integration tasks only after component tasks complete
   - Explicitly call out parallel vs sequential dependencies in task table
```

### Recommended Addition to WORKER_PROMPT_TEMPLATE.md

Add new section after "Performance Requirements" (line 100):

```markdown
### Backward Compatibility

[Include when task modifies existing data formats or APIs]
- **API Changes**: [How to maintain compatibility during transition]
- **Data Format Changes**: [How existing data migrates to new format]
- **Parallel Code Paths**: [If old and new code must coexist temporarily]
- **Deprecation Strategy**: [What gets deprecated and when]
- **Feature Flags**: [How to enable/disable new behavior for staged rollout]
```

Add to "Checklist for New Worker Prompts" (after line 322):

```markdown
- [ ] If task changes data format, backward compatibility section included
- [ ] If task is high-risk (Medium/High), mitigation strategy specified
- [ ] If task depends on other in-progress work, conflicts identified in "Do NOT" section
```

### Recommended Update to instructions_orchestrator.md

Add to "Available Plan Documents" (line 19):

```markdown
- **`docs/EXTRACTION_IMPROVEMENT_PLAN.md`** - Unified extraction architecture (EI-series tasks)
```

---

## References

- **Diagnostic Analysis**: `/Users/rgmarkey/.claude/plans/majestic-rolling-meadow.md`
- **Current Code**:
  - `src/extraction/value_extractor.py` - Needs FalsePositiveFilter + TableRowParser integration
  - `src/review/candidate_generator.py` - Has proven filter implementations to reuse
  - `src/extraction/html_segmenter.py` - Needs cell boundary markers
  - `src/review/table_structure.py` - TableRowParser to integrate
  - `src/review/false_positive_filter.py` - Filter to integrate
- **Related Plans**:
  - `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` - ReviewCandidate integration
  - `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - May affect classification
- **Architecture**:
  - `docs/architecture/system-overview.md` - Overall system context
  - `CLAUDE.md` - Current pipeline flow

---

**Last Updated**: 2025-12-17
**Next Review**: After EI-3 completion (verify filter integration works correctly)

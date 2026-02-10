# WORKER PROMPT: Task DFP-1 - Fix Date False Positive Filtering Gaps

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DFP-1
TASK NAME:     Fix date false positive filtering to catch "Month DD" patterns without year
WORKSTREAM:    Bug Fix - False Positive Elimination
SOURCE:        User report: dates from Snowflake filing being flagged as candidates
STATUS:        🟡 PENDING
COMPLETION:    [To be filled on completion]
TIME ESTIMATE: 1-2 hours (investigation done, implementation ~45 min, testing ~45 min)
TIME ACTUAL:   [To be filled on completion]
RISK LEVEL:    Low - Patterns become more restrictive (filters more), no valid metrics affected
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-1 through UXI-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Fix two bugs causing date-related false positives in review candidates:
1. "31" from "January 31," in table headers is not filtered (missing date pattern)
2. "9202020192020" garbage from `[ROW]` marker stripping losing spaces

**Business Rationale**: Reviewers waste time rejecting obvious date false positives. The Snowflake filing has multiple candidates where day numbers (31, 30) from fiscal period headers are flagged as metrics.

**Current Behavior**:
- "January 31," pattern NOT matched because all date patterns require 4-digit year
- `[ROW]` markers replaced with empty string, causing adjacent values to concatenate

**Desired Behavior**:
- "31" from "January 31," filtered as "part_of_date"
- `[ROW]` markers replaced with space, preserving word boundaries

## Prerequisites

- None (standalone bug fix)

## Files to Modify

1. **`src/review/false_positive_filter.py`** - Add "Month DD" date pattern to DATE_CONTEXT_PATTERNS
2. **`src/extraction/context_extractor.py`** - Fix ROW marker stripping to preserve spacing
3. **`tests/unit/review/test_false_positive_filter.py`** - Add test cases for "Month DD" pattern
4. **`tests/unit/extraction/test_context_extractor.py`** - Add/update marker stripping tests

## Files to Read (Context Only)

- `src/review/candidate_generator.py` - Understand how false positive filter is invoked
- `src/extraction/html_segmenter.py` - Understand where [ROW]/[CELL] markers originate

## Implementation Requirements

### Core Functionality

1. **Add "Month DD" Date Pattern** (false_positive_filter.py)
   - Add new pattern to `DATE_CONTEXT_PATTERNS` list (around line 154)
   - Pattern must match: "January 31,", "June 30,", "September 30", "Jul 31", etc.
   - Pattern must be case-insensitive
   - Pattern must handle optional comma after day
   - Pattern must NOT require a year to follow
   - Use word boundary `\b` to prevent matching "January 31st" incorrectly

   ```python
   # New pattern to add (reference only):
   re.compile(
       r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
       r"Sep(?:t(?:ember)?|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2}\b",
       re.IGNORECASE,
   ),
   ```

2. **Fix ROW Marker Stripping** (context_extractor.py line 247)
   - Current: `text = self.ROW_MARKER_PATTERN.sub("", text)`
   - Fixed: `text = self.ROW_MARKER_PATTERN.sub(" ", text)`
   - The `" ".join(text.split())` on line 249 will normalize multiple spaces

### Error Handling

- No new error handling required (existing patterns handle malformed input)
- Regex patterns should not throw exceptions (already handled by re module)

### Performance Requirements

- No performance impact expected (single additional regex pattern)
- Pattern matching is O(n) where n = text length

## Test Requirements

### Coverage Target: **≥ 90%** for modified code in both modules

### Test Categories (10+ tests recommended)

1. **Date Pattern Tests** (5-6 tests in test_false_positive_filter.py)
   - "January 31," → "31" filtered as part_of_date
   - "June 30," → "30" filtered as part_of_date
   - "September 30" (no comma) → "30" filtered
   - "Jul 31" (abbreviated) → "31" filtered
   - "Fiscal Year Ended January 31," → "31" filtered
   - "Six Months Ended July 31," → "31" filtered
   - Ensure real metrics like "31 million customers" are NOT filtered

2. **Marker Stripping Tests** (4-5 tests in test_context_extractor.py)
   - `"2019 [ROW] 2020"` → `"2019 2020"` (space preserved)
   - `"Header [ROW] Data"` → `"Header Data"` (not "HeaderData")
   - Multiple markers: `"A [ROW] B [ROW] C"` → `"A B C"`
   - Existing `[CELL]` tests still pass (no regression)
   - Combined: `"A [CELL] B [ROW] C [CELL] D"` → `"A | B C | D"`

### Known Edge Cases to Test

- Month abbreviations: "Jan", "Feb", etc.
- Comma variations: "January 31," vs "January 31" (both should match)
- No false positives on: "31 million", "31%", "$31"

## Gold Standard Validation

This task affects `src/review/false_positive_filter.py` which is in the metric identification path.

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal validation (must pass before commit)
pytest -m gold_standard --gold-standard-mode=fresh -v
```

### Regression Handling

- Expected: Precision should IMPROVE (fewer date FPs)
- Expected: Recall should remain UNCHANGED (no valid metrics affected)
- If recall drops: investigate - we may be over-filtering

## Acceptance Criteria

- [ ] New "Month DD" pattern added to DATE_CONTEXT_PATTERNS
- [ ] "31" from "January 31," is filtered with reason "part_of_date"
- [ ] ROW marker stripping preserves spacing (replaces with " " not "")
- [ ] **10+ unit tests** covering date patterns and marker stripping
- [ ] **Test coverage ≥ 90%** for modified lines
- [ ] All new tests pass
- [ ] All existing tests still pass (no regression)
- [ ] Gold standard validation passes
- [ ] `mypy src/review/false_positive_filter.py src/extraction/context_extractor.py --strict` passes

## Do NOT

- Modify `src/review/candidate_generator.py` (only filter is changing)
- Modify `src/extraction/html_segmenter.py` (markers are correctly generated there)
- Change existing DATE_CONTEXT_PATTERNS (only ADD new pattern)
- Remove or alter the CELL marker handling (only fix ROW handling)

## Verification Commands

```bash
# Run false positive filter tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py -v

# Run context extractor tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_context_extractor.py -v -k "marker"

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_false_positive_filter.py \
  tests/unit/extraction/test_context_extractor.py \
  --cov=src/review/false_positive_filter --cov=src/extraction/context_extractor \
  --cov-report=term-missing

# Type safety check
mypy src/review/false_positive_filter.py src/extraction/context_extractor.py --strict

# Gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh -v

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ tests/unit/extraction/ --no-cov -q
```

## Critical Evaluation Phase

**Task Size: S** - Standard evaluation: review checklist, identify 1-2 improvements max

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] DRY principle followed
- [ ] Naming conventions match existing patterns

### 2. Test Coverage Assessment
- [ ] Edge cases covered (month abbreviations, comma variations)
- [ ] Negative test cases exist (real metrics not filtered)

### 3. Architecture Alignment
- [ ] Follows existing DATE_CONTEXT_PATTERNS style
- [ ] Uses same regex conventions as existing patterns

### 4. User Approval
**STOP and ask user** before committing if any improvements identified.

## Expected Impact

**Before DFP-1**:
- Snowflake candidates 2739, 2750 show "31" as false positive candidates
- Candidates like 2741 show "9202020192020" garbage

**After DFP-1**:
- Day numbers from "Month DD," patterns filtered as "part_of_date"
- Context text preserves spaces between values
- Fewer false positives in review queue

## Reference

- **Issue source**: User report during UXI-1 testing (Snowflake filing candidate #25)
- **Root cause investigation**: 3 Explore agents confirmed patterns and marker stripping
- **Related**: HRV-10/HRV-11 (financial statement filtering), EI-2 (measurement unit patterns)

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6

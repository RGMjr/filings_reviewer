# WORKER PROMPT: Task EI-1 - Filter Definition Segments

```
===============================================================================
TASK ID:       EI-1
TASK NAME:     Filter out definition segments from candidate generation
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 - Issue #1
STATUS:        PENDING
COMPLETION:    [Will be: docs/completion/EI-1_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 1 hour (implementation 30 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Simple filter using existing flag, additive change only
PARALLEL WITH: EI-2, EI-3 (all independent Phase 1 tasks)
===============================================================================
```

## Objective

Prevent segments containing definition language ("We define X as...", "X is defined as...") from generating review candidates, eliminating false positives from metric definitions.

**Business Rationale**: Definitions explain what metrics mean but don't disclose actual values. Currently "We define daily active users as users active in a 24-hour period" generates a candidate with value "24", wasting reviewer time on non-disclosure segments.

**Current Behavior**: Definition segments generate candidates. The `contains_definition_flag` is detected by `feature_extractor.py` but ignored during candidate generation.

**Desired Behavior**: Segments with `contains_definition_flag=True` generate zero candidates.

## Prerequisites

- None (standalone fix)
- Understand how `contains_definition_flag` is set in `SegmentDict` (already populated by extraction pipeline)

## Files to Modify

1. **`src/review/candidate_generator.py`** - Add early-exit check for definition segments in `_process_segment()` method (after line 512)

## Files to Read (Context Only)

- `src/review/models.py` - Understand `SegmentDict` TypedDict structure (line 100 shows `contains_definition_flag`)
- `src/review/feature_extractor.py` - See how definition language is detected (lines 131-141, 359-372)
- `src/extraction/models.py` - Understand `SourceSegment` structure

## Implementation Requirements

### Core Functionality

1. **Definition Segment Filter**
   - Check if `segment.get("contains_definition_flag")` is `True` at the start of `_process_segment()`
   - If True, return empty candidates list with stats immediately (early exit)
   - Log the skip reason at DEBUG level for debugging/validation
   - Location: After the text validation checks (around line 512), before `_find_numbers()`

2. **Expected Location in _process_segment()**
   ```python
   # After line 512: if not text: return [], segment_stats
   # Before line 524: numbers = self._find_numbers(text)

   # Skip definition segments - they explain metrics but don't contain values
   if segment.get("contains_definition_flag"):
       logger.debug(
           f"Skipping definition segment {source_segment_id}: "
           "contains_definition_flag is True"
       )
       return [], segment_stats
   ```

3. **Default Behavior**
   - If `contains_definition_flag` is missing or None, proceed normally (don't filter)
   - Use `.get()` to avoid KeyError on legacy segments

### Error Handling

- **Missing flag**: If `contains_definition_flag` not present in segment dict, default to `False` (don't filter)
- **None value**: Treat `None` same as `False` (don't filter)
- **No exceptions**: Use `.get()` with no default - falsy check handles all cases

### Performance Requirements

- Negligible overhead (single dict lookup before processing)
- Filter check is O(1) and happens before expensive keyword/number matching

## Test Requirements

### Coverage Target: **Maintain ≥90%** for `src/review/candidate_generator.py`

### Test Categories (4-5 tests recommended)

1. **Definition Filtering** (4 tests)
   - `test_definition_segment_generates_no_candidates` - Segment with `contains_definition_flag=True` and numbers returns empty list
   - `test_non_definition_segment_generates_candidates` - Segment with `contains_definition_flag=False` generates candidates normally
   - `test_missing_definition_flag_generates_candidates` - Segment without `contains_definition_flag` key generates candidates normally
   - `test_definition_flag_none_generates_candidates` - Segment with `contains_definition_flag=None` generates candidates normally

2. **Logging Verification** (optional)
   - Verify DEBUG log message includes segment_id when filtering

### Test File Location

Add tests to: `tests/unit/review/test_candidate_generator.py`

### Test Class/Function Names

```python
class TestDefinitionFiltering:
    """EI-1: Definition segment filtering tests."""

    def test_definition_segment_generates_no_candidates(self):
        ...

    def test_non_definition_segment_generates_candidates(self):
        ...

    def test_missing_definition_flag_generates_candidates(self):
        ...

    def test_definition_flag_none_generates_candidates(self):
        ...
```

## Acceptance Criteria

- [ ] Definition segments (`contains_definition_flag=True`) generate 0 candidates
- [ ] Non-definition segments (`contains_definition_flag=False`) generate candidates normally
- [ ] Missing flag defaults to non-filtering behavior (backward compatible)
- [ ] 4+ unit tests covering all flag states (True, False, None, missing)
- [ ] All existing tests still pass (no regressions)
- [ ] NO changes to `feature_extractor.py` or other modules
- [ ] NO changes to definition detection logic
- [ ] Coverage maintained ≥90% for `candidate_generator.py`
- [ ] Type safety maintained (`mypy src/review/candidate_generator.py --strict` passes)

## Do NOT

- Modify `feature_extractor.py` (definition detection logic is correct as-is)
- Change definition patterns or detection (out of scope)
- Add new configuration parameters (simple if-statement is sufficient)
- Modify `SegmentDict` TypedDict or add new fields
- Add dependencies on new modules
- Filter based on text content regex (use existing flag only)

## Verification Commands

```bash
# Run new tests specifically
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py::TestDefinitionFiltering -v

# Verify no regressions in candidate generator tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py --no-cov -q

# Check coverage is maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py \
  --cov=src/review/candidate_generator --cov-report=term-missing -q

# Type safety check
mypy src/review/candidate_generator.py --strict

# Full review module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Expected Impact

**Before EI-1**:
- "We define daily active users as users active in a 24-hour period" generates candidate with value "24"
- Definition segments waste reviewer time
- False positives from measurement unit numbers in definitions

**After EI-1**:
- Definition segments generate 0 candidates
- Only actual metric disclosures reviewed
- Estimated 5-10% reduction in false positive candidates

## Post-Implementation Tasks

After completing EI-1:

1. **Create Completion Summary**:
   - Create `docs/completion/EI-1_COMPLETION_SUMMARY.md` with:
     - Summary of changes made
     - Test results and coverage
     - Any deviations from plan
     - Commit hash

2. **Update Documentation**:
   - Mark EI-1 as COMPLETE (✅) in `docs/EXTRACTION_IMPROVEMENT_PLAN.md` task table
   - Update status from 🟡 PENDING to ✅ COMPLETE with date

3. **Archive This Prompt**:
   - Move this file to `docs/archive/workstreams/EI-extraction-improvements/WORKER_PROMPT_TASK_EI-1.md`
   - Create the `EI-extraction-improvements` directory if it doesn't exist

4. **Commit and Push**:
   ```bash
   # Stage changes
   git add src/review/candidate_generator.py \
           tests/unit/review/test_candidate_generator.py \
           docs/EXTRACTION_IMPROVEMENT_PLAN.md \
           docs/completion/EI-1_COMPLETION_SUMMARY.md

   # Commit with descriptive message
   git commit -m "EI-1: Filter definition segments from candidate generation

   Add early-exit check in _process_segment() to skip segments where
   contains_definition_flag=True. Definition segments explain what metrics
   mean but don't disclose actual values, so generating candidates from
   them wastes reviewer time.

   - Check contains_definition_flag before processing
   - Return empty candidates list for definition segments
   - Log skip reason at DEBUG level
   - Backward compatible: missing flag defaults to non-filtering

   Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"

   git push origin main
   ```

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Problem 4 (Definition Language)
- **Dependencies**: None (first task in Phase 1)
- **Related tasks**:
  - EI-2 (Measurement Unit Patterns) - can run in parallel
  - EI-3 (FalsePositiveFilter Integration) - can run in parallel
  - EI-6 (Integration Testing) - depends on this task
- **Definition detection**: Already implemented in `feature_extractor.py:131-141`

---

**Last Updated**: 2025-12-17
**Format Version**: 2.2 (concise requirements-focused format)

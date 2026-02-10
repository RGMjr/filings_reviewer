# WORKER PROMPT: Task DUP-3 - Deduplicator and Helpers Integration

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DUP-3
TASK NAME:     Update deduplicator to return suppressed candidates and integrate logging in helpers
WORKSTREAM:    Human Review System Improvements
SOURCE:        Slack filing duplicate candidates analysis (snuggly-watching-micali.md)
STATUS:        ✅ COMPLETE (SIMPLIFIED)
COMPLETION:    2026-01-07
TIME ESTIMATE: 2-3 hours (original)
TIME ACTUAL:   30 minutes (simplified approach)
RISK LEVEL:    Low (extending existing functions, not changing core logic)
TASK SIZE:     S (was M before simplification)
DEPENDS ON:    DUP-2 (Upsert Logic and Suppression Logging)
UNLOCKS:       P2-UF-1 (Unit-Based Metric Filtering)
BLOCKS:        P2-UF-1
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## ⚠️ DESIGN DECISION: Task Simplified

**Original Approach** (Not Implemented):
- Modify `deduplicate_candidates()` to return suppressed candidates with winners
- Add `return_suppressed=True` parameter for backward compatibility
- Track 'cross_sentence' and 'lower_confidence' suppression reasons
- Have `helpers.py` log suppressions after database insert

**Problem Identified During Critical Evaluation**:
1. **Redundancy**: DUP-2 already implemented suppression logging in `bulk_insert_review_candidates(log_suppressed=True)`
2. **Double Deduplication**: In-memory dedup happens BEFORE DB insert, but DB also deduplicates
3. **Winner ID Timing**: At in-memory dedup time, candidates don't have database IDs yet
4. **Double-Logging Risk**: Both layers could log the same suppression with different reasons

**Simplified Approach** (Implemented):
- Added `log_suppressed` parameter to `generate_candidates_for_filing()` in `helpers.py`
- Passes through to `bulk_insert_review_candidates(log_suppressed=True)`
- Captures 'lower_confidence' and 'runner_up' reasons from DB layer only

**Trade-off Accepted**:
- Does NOT capture 'cross_sentence' reason from P1.6 same-sentence preference
- Provides ~90% of suppression tracking value with minimal code complexity
- Full documentation in module docstring for future reference

**Files Modified**:
- `src/review/helpers.py` - Added `log_suppressed` parameter
- `tests/unit/review/test_helpers.py` - Added 7 tests (TestSuppressionLogging class)
- `docs/PROJECT_TASK_INVENTORY.md` - Completion notes

---

## Original Objective (Archived for Reference)

## Objective

Modify `deduplicate_candidates()` to return suppressed candidates alongside winners, and integrate suppression logging into the candidate generation workflow.

**Business Rationale**: In-memory deduplication already happens before database insert, but we're not capturing which candidates were suppressed or why. By tracking this, we can learn from human review decisions - if a reviewer reclassifies a winner to a metric that matches a suppressed candidate, our confidence scoring may be wrong.

**Current Behavior**:
- `deduplicate_candidates()` returns `(unique_candidates, duplicates_removed_count)`
- Suppressed candidates are discarded silently
- No connection between in-memory dedup and database suppression logging

**Desired Behavior**:
1. `deduplicate_candidates()` returns suppressed candidates with their winners
2. `generate_candidates_for_filing()` logs suppressions to database
3. Both in-memory and database-level suppressions are logged

## Prerequisites

- DUP-1 complete (suppressed_candidates table exists)
- DUP-2 complete (suppression logging methods available in DatabaseAdapter)

## Files to Create

None

## Files to Modify

1. **`src/review/deduplicator.py`** - Modify `deduplicate_candidates()` to return suppressed candidates
2. **`src/review/helpers.py`** - Integrate suppression logging in `generate_candidates_for_filing()`
3. **`tests/unit/review/test_deduplicator.py`** - Add tests for suppression tracking

## Files to Read (Context Only)

- `src/review/deduplicator.py` - Current implementation (159 lines)
- `src/review/helpers.py` - Current generate_candidates_for_filing() implementation
- `src/review/models.py` - ReviewCandidate model

## Implementation Requirements

### Core Functionality

1. **Modify `deduplicate_candidates()` Return Value**
   - Current: `tuple[list[ReviewCandidate], int]` - (unique, removed_count)
   - New: `tuple[list[ReviewCandidate], list[tuple[ReviewCandidate, ReviewCandidate, str]]]`
   - Second element is list of (suppressed_candidate, winner_candidate, reason)
   - Reason: 'lower_confidence' or 'cross_sentence'
   - Backward compatibility: Add optional parameter `return_suppressed: bool = False`
   - When False, return original format; when True, return new format

2. **Suppression Reason Logic**
   - 'cross_sentence': Candidate suppressed because winner was same-sentence (P1.6)
   - 'lower_confidence': Candidate suppressed due to lower confidence score
   - Track which reason applies during dedup loop

3. **Integrate in `generate_candidates_for_filing()`**
   - Call `deduplicate_candidates()` with `return_suppressed=True`
   - After database insert, log suppressed candidates using `db.bulk_log_suppressed_candidates()`
   - Map winner candidates to their database IDs after insert
   - Handle case where winner_candidate_id might not be available yet

### Error Handling

- If suppression logging fails, log warning but don't fail the generation
- Suppression logging is non-critical - generation should complete even if logging fails
- Handle empty suppressed list gracefully

### Backward Compatibility

- **Default behavior unchanged**: `return_suppressed=False` by default
- Existing callers continue to work without modification
- Only callers that explicitly request suppression tracking get new behavior

## Test Requirements

### Coverage Target: **≥ 95%** for `deduplicator.py` (maintain existing high coverage)

### Test Categories (10+ tests recommended)

1. **Suppression Tracking Tests** (4-5 tests)
   - Suppressed candidates captured with correct winner
   - Suppression reason correctly identified ('cross_sentence' vs 'lower_confidence')
   - Multiple suppressions in same group handled
   - Empty suppression list when no duplicates

2. **Backward Compatibility Tests** (2-3 tests)
   - `return_suppressed=False` returns original format
   - Existing test cases still pass unchanged
   - Count matches number of suppressed candidates

3. **Integration Tests** (3-4 tests)
   - Full workflow: generate -> dedup -> insert -> log suppressions
   - Suppressed candidates appear in suppressed_candidates table
   - Winner candidate IDs correctly linked

### Known Edge Cases to Test

- Group where all candidates are same-sentence (no cross_sentence suppression)
- Group where winner has NULL confidence
- Single-element groups (no suppression)

## Acceptance Criteria

- [ ] `deduplicate_candidates()` tracks suppressed candidates when `return_suppressed=True`
- [ ] Suppression reasons correctly identified
- [ ] `generate_candidates_for_filing()` logs suppressions to database
- [ ] Backward compatible - existing callers work unchanged
- [ ] **10+ unit tests** for deduplicator suppression tracking
- [ ] **Test coverage ≥ 95%** for `src/review/deduplicator.py`
- [ ] All new tests pass
- [ ] All existing deduplicator tests still pass
- [ ] Integration test verifies end-to-end suppression logging

## Do NOT

- Change the deduplication logic itself (keep existing scoring hierarchy)
- Break backward compatibility for existing callers
- Make suppression logging a blocking operation
- Modify `src/infra/db.py` (that's DUP-2)

## Verification Commands

```bash
# Run deduplicator tests
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_deduplicator.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_deduplicator.py \
  --cov=src/review/deduplicator --cov-report=term-missing --cov-fail-under=95

# Run integration test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -v --no-cov

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues
- [ ] Function documentation updated with new return type
- [ ] Type hints complete and accurate

### 2. Test Coverage Assessment
- [ ] All suppression reason cases tested
- [ ] Edge cases covered
- [ ] Integration verified

### 3. Architecture Alignment
- [ ] Follows existing deduplicator patterns
- [ ] Non-blocking suppression logging
- [ ] Proper error handling

### 4. User Approval (REQUIRED)
**STOP and ask the user** before committing.

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
def deduplicate_candidates(
    candidates: list[ReviewCandidate],
    prefer_same_sentence: bool = True,
    return_suppressed: bool = False,  # NEW parameter
) -> tuple[list[ReviewCandidate], int] | tuple[list[ReviewCandidate], list[tuple[ReviewCandidate, ReviewCandidate, str]]]:
    """
    Deduplicate candidates, optionally tracking suppressed candidates.

    Args:
        candidates: List of candidates to deduplicate
        prefer_same_sentence: P1.6 preference
        return_suppressed: If True, return suppressed candidates with reasons

    Returns:
        If return_suppressed=False: (unique_candidates, removed_count)
        If return_suppressed=True: (unique_candidates, [(suppressed, winner, reason), ...])
    """
    # ... existing grouping logic ...

    suppressed_with_reasons = []  # NEW: track suppressions

    for group in groups.values():
        if len(group) == 1:
            deduplicated.append(group[0])
        else:
            # Track which were suppressed and why
            # ... existing winner selection logic ...
            winner = sorted_group[0]
            for loser in sorted_group[1:]:
                reason = 'cross_sentence' if (was_filtered_by_same_sentence) else 'lower_confidence'
                suppressed_with_reasons.append((loser, winner, reason))
            deduplicated.append(winner)

    if return_suppressed:
        return deduplicated, suppressed_with_reasons
    else:
        return deduplicated, len(suppressed_with_reasons)
```
</details>

## Reference

- **Issue source**: Slack filing duplicate candidates analysis
- **Dependencies**: DUP-1, DUP-2
- **Related**: P2-UF-1 (future unit-based filtering)

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

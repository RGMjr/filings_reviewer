# Task DUP-2 Completion Report

```markdown
===============================================================================
TASK ID:        DUP-2
TASK NAME:      Add upsert logic to bulk_insert_review_candidates with runner-up capture
COMPLETED:      2026-01-07
COMPLETED BY:   Claude Code
TIME ESTIMATE:  5-6 hours
TIME ACTUAL:    ~5 hours
VARIANCE:       Within estimate
FILES CHANGED:  4
TESTS ADDED:    25
===============================================================================
```

## Summary

Implemented two-phase conflict resolution algorithm in `bulk_insert_review_candidates()` to handle duplicate candidates idempotently. The system now keeps highest-confidence candidates on conflict, logs suppressed alternatives to the `suppressed_candidates` table, and captures runner-up metrics for UI quick-select functionality.

## Changes Made

### Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `src/infra/db.py` | +809 | Two-phase algorithm with helper methods |
| `sql/08_add_suppressed_candidates.sql` | +3/-1 | Added 'runner_up' to constraint |
| `tests/integration/conftest.py` | +2 | Test fixtures for suppressed_candidates |

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `tests/integration/test_db_upsert.py` | 686 | Comprehensive upsert behavior tests |

### Key Code Changes

- **`_fetch_conflicting_candidates()`** (`db.py:1076`) - Pre-fetch existing candidates matching uniqueness keys, handles both NULL and non-NULL `source_segment_id` cases separately for partial index compatibility
- **`_bulk_log_suppressed()`** (`db.py:1168`) - Bulk insert suppressed candidates using UNNEST pattern
- **`_identify_runner_ups()`** (`db.py:1297`) - Find best alternative metric at each position for UI quick-select
- **`bulk_insert_review_candidates()`** (`db.py:1416`) - Enhanced with three-phase algorithm:
  - Phase 1: Within-batch deduplication (highest confidence wins)
  - Phase 2: Database conflict resolution (pre-fetch + compare)
  - Phase 3: Runner-up capture (best alternative metric logged)
- **Constraint update** - Added `'runner_up'` to `check_suppression_reason` enum

## Test Coverage

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Test Count | 0 | 25 | +25 |
| Pass Rate | N/A | 100% | - |

### Tests Added

**Basic Insert (3 tests)**
- `test_insert_single_new` - Single new candidate inserted
- `test_insert_multiple_new` - Multiple new candidates, no conflicts
- `test_insert_empty_list` - Empty list returns empty result

**Conflict: New Loses (3 tests)**
- `test_conflict_new_lower_confidence` - Lower confidence loses to existing
- `test_conflict_new_equal_confidence` - Ties go to existing (first wins)
- `test_conflict_multiple_losers` - Multiple candidates losing to existing

**Conflict: New Wins (3 tests)**
- `test_conflict_new_higher_confidence` - Higher confidence wins
- `test_conflict_winner_replaces_existing` - Verify UPDATE happened
- `test_conflict_old_values_captured` - Old values logged correctly

**Runner-Up Capture (4 tests)**
- `test_runner_up_captured` - Alternative metric logged as runner-up
- `test_runner_up_different_metric_only` - Same metric = lower_confidence, not runner-up
- `test_runner_up_highest_alternative` - Best alternative selected
- `test_runner_up_linked_to_winner` - FK relationship verified

**NULL Segment Handling (3 tests)**
- `test_null_segment_conflict` - NULL segment conflicts resolved
- `test_mixed_null_and_not_null` - Both cases in same batch
- `test_null_segment_runner_up` - Runner-up with NULL segment

**Return Contract (2 tests)**
- `test_return_length_matches_input` - len(result) == len(input)
- `test_return_order_preserved` - Order preserved for zip(strict=True)

**Additional Coverage (7 tests)**
- Edge cases: confidence boundaries, Decimal vs float comparison
- Backward compatibility: log_suppressed=False returns list[int]
- Transaction integrity: partial failures don't leave orphans

## Verification Results

```bash
# Command run:
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_db_upsert.py -v

# Output summary:
25 passed in 4.2s
```

### Acceptance Criteria Checklist

- [x] `bulk_insert_review_candidates()` uses two-phase conflict resolution
- [x] Return value length ALWAYS equals input length
- [x] Return value order matches input order
- [x] Higher-confidence candidates win conflicts
- [x] Existing row wins ties (equal confidence)
- [x] Suppressed candidates logged with correct reason
- [x] Runner-up captured for positions with multiple metrics
- [x] Runner-up has different `suggested_metric_id` than winner
- [x] NULL `source_segment_id` handled correctly (separate from non-NULL)
- [x] `suppression_reason` constraint updated to include 'runner_up'
- [x] Backward compatible: `log_suppressed=False` returns `list[int]` only
- [x] **25 unit tests** covering all scenarios (exceeds 18+ requirement)
- [x] All existing tests still pass
- [x] `helpers.py` caller works unchanged

## Evaluation Findings

### Code Quality
- [x] No linting/type issues
- [x] DRY followed (helper methods extracted)
- [x] Comprehensive docstrings on all new methods

### Test Assessment
- [x] Edge cases covered (NULL segments, confidence boundaries, Decimal types)
- [x] Negative tests exist (conflict scenarios, empty inputs)
- [x] Integration with existing code tested

### Architecture Alignment
- [x] Follows DatabaseAdapter patterns
- [x] Uses UNNEST for bulk operations (project standard)
- [x] Proper transaction handling (single transaction)

### Improvements Identified
1. **Decimal vs float comparison** - Fixed during implementation (Implemented)
2. **UXI-ALT UI integration** - Show runner-up in review interface (Deferred to future task)

### User Decisions
- Approved: Core implementation as specified
- Deferred: UI integration for runner-up display (separate task UXI-ALT)

## Impact

### Before Task
- Re-running candidate generation created duplicate candidates
- No mechanism to capture alternative metric suggestions
- Callers had to handle duplicates externally

### After Task
- Idempotent: re-running produces same result
- Higher-confidence candidates automatically win
- Runner-up metrics captured for faster reclassification in UI
- Return contract preserved: `zip(candidates, result_ids, strict=True)` is safe

## Unlocked Tasks

Tasks now available after this completion:

- **DUP-3** - Deduplicator helpers integration (completed same day)
- **UXI-ALT** - Alternative metric UI display (future)

## References

- **Worker Prompt**: `docs/archive/worker-prompts-completed/WORKER_PROMPT_TASK_DUP-2_REVISED.md`
- **Original Prompt (superseded)**: `docs/archive/worker-prompts-superseded/DUP-2_upsert_logic_suppression_logging.md`
- **Related Commits**: `0201d10` (feat(DUP-2): Add upsert logic with conflict resolution and runner-up capture)
- **Dependency**: DUP-1 (schema migration)
- **Unlocked**: DUP-3 (helpers integration)

---

**Report Generated**: 2026-01-07
**Report Version**: 1.1

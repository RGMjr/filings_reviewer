# WORKER PROMPT: Task DUP-2 - Upsert Logic and Suppression Logging

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DUP-2
TASK NAME:     Add upsert logic to bulk_insert_review_candidates and suppression logging
WORKSTREAM:    Human Review System Improvements
SOURCE:        Slack filing duplicate candidates analysis (snuggly-watching-micali.md)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 4-5 hours (investigation 1h, implementation 2h, testing 2h)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (modifies core database adapter method)
TASK SIZE:     L
DEPENDS ON:    DUP-1 (Database Schema Migration)
UNLOCKS:       DUP-3 (Deduplicator and Helpers Integration)
BLOCKS:        DUP-3
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Modify `bulk_insert_review_candidates()` to use upsert logic that keeps the higher-confidence candidate on conflict, and add method to log suppressed candidates.

**Business Rationale**: When candidate generation runs twice (intentionally or accidentally), we want the system to be idempotent - keeping the best candidate and logging the suppressed alternative for potential learning.

**Current Behavior**: `bulk_insert_review_candidates()` uses plain INSERT, creating duplicates on re-run.

**Desired Behavior**:
1. On conflict, compare confidence and keep higher-confidence candidate
2. Log suppressed candidate to `suppressed_candidates` table
3. Return information about what was inserted vs updated

## Prerequisites

- DUP-1 complete (unique indexes and suppressed_candidates table exist)
- Run: `\d suppressed_candidates` to verify table exists

## Files to Create

1. **`tests/unit/infra/test_db_upsert.py`** - Unit tests for upsert behavior

## Files to Modify

1. **`src/infra/db.py`** - Modify `bulk_insert_review_candidates()`, add `log_suppressed_candidate()` and `bulk_log_suppressed_candidates()`

## Files to Read (Context Only)

- `src/infra/db.py` - Current bulk_insert_review_candidates implementation (lines 1072-1200)
- `src/review/models.py` - ReviewCandidate and CandidateFeatures models
- `sql/08_add_suppressed_candidates.sql` - suppressed_candidates table schema

## Implementation Requirements

### Core Functionality

1. **Modify `bulk_insert_review_candidates()`**
   - Change return type to `tuple[list[int], list[dict]]` - (inserted_ids, suppressed_candidates_data)
   - Use `ON CONFLICT ... DO UPDATE` with confidence comparison
   - When new candidate has HIGHER confidence: update existing row, log old as suppressed
   - When new candidate has LOWER or EQUAL confidence: skip update, log new as suppressed
   - Handle partial indexes (separate logic for NULL vs non-NULL source_segment_id)
   - Return list of suppressed candidate data for caller to log

2. **New Method: `log_suppressed_candidate()`**
   - Insert single suppressed candidate record
   - Parameters: winner_candidate_id, suppressed_data dict, suppression_reason, winner_confidence
   - Return suppressed_id

3. **New Method: `bulk_log_suppressed_candidates()`**
   - Efficient bulk insert for multiple suppressed candidates
   - Use UNNEST pattern like existing bulk methods
   - Parameters: list of suppressed candidate dicts with reason and winner info

4. **Backward Compatibility**
   - Existing callers of `bulk_insert_review_candidates()` should continue to work
   - Make suppression logging opt-in via parameter: `log_suppressed: bool = False`
   - When `log_suppressed=False`, return only `list[int]` (original behavior)
   - When `log_suppressed=True`, return `tuple[list[int], int]` (ids, suppressed_count)

### Error Handling

- **Unique constraint violation**: Should not occur with proper upsert, but catch and log if it does
- **NULL confidence values**: Treat as lower than any numeric confidence
- **Transaction integrity**: All inserts/updates in single transaction
- **Partial failures**: If bulk insert fails, no partial data should remain

### Performance Requirements

- Bulk insert performance should not degrade significantly (benchmark against current)
- Suppression logging should be efficient (bulk insert, not row-by-row)
- Target: <100ms for 100 candidates

## Test Requirements

### Coverage Target: **≥ 90%** for new/modified methods

### Test Categories (15+ tests recommended)

1. **Upsert Behavior Tests** (5-6 tests)
   - New candidate inserted when no conflict
   - Higher-confidence new candidate replaces existing
   - Lower-confidence new candidate is suppressed
   - Equal confidence: existing wins (first-wins tiebreaker)
   - NULL confidence handling (NULL < any numeric)

2. **Suppression Logging Tests** (4-5 tests)
   - Suppressed candidate logged with correct reason
   - Winner candidate ID linked correctly
   - Winner confidence captured at suppression time
   - Bulk logging works for multiple suppressions

3. **Backward Compatibility Tests** (3-4 tests)
   - Existing callers with log_suppressed=False work unchanged
   - Return type matches original when log_suppressed=False
   - No suppressed_candidates entries created when log_suppressed=False

4. **Edge Cases** (3-4 tests)
   - NULL source_segment_id candidates
   - Mixed NULL and non-NULL in same batch
   - Empty candidate list
   - Single candidate (no conflict possible)

### Known Edge Cases to Test

- Candidate with NULL source_segment_id conflicting with another NULL segment_id candidate
- Confidence values at boundaries (0.0, 1.0, NULL)
- Very long context_text or triggering_keyword values

## Acceptance Criteria

- [ ] `bulk_insert_review_candidates()` uses upsert logic with confidence comparison
- [ ] `log_suppressed_candidate()` method added
- [ ] `bulk_log_suppressed_candidates()` method added
- [ ] Backward compatible - existing callers work unchanged
- [ ] Higher-confidence candidates win on conflict
- [ ] Suppressed candidates logged with correct reason
- [ ] **15+ unit tests** covering upsert, logging, and edge cases
- [ ] **Test coverage ≥ 90%** for modified methods
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy src/infra/db.py --strict` passes (where applicable)

## Do NOT

- Modify existing return type for callers using `log_suppressed=False` (default)
- Change method signature in breaking way
- Add new dependencies
- Modify review_candidates table schema (that's DUP-1)

## Verification Commands

```bash
# Run new tests
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_upsert.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_upsert.py \
  --cov=src/infra/db --cov-report=term-missing

# Verify existing tests still pass
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_db_review_methods.py -v --tb=short

# Type check
mypy src/infra/db.py --strict 2>&1 | head -20
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] Method documentation complete
- [ ] Error handling appropriate

### 2. Test Coverage Assessment
- [ ] All edge cases from requirements covered
- [ ] Negative test cases exist
- [ ] Integration with existing code tested

### 3. Architecture Alignment
- [ ] Follows existing DatabaseAdapter patterns
- [ ] Uses UNNEST for bulk operations (project standard)
- [ ] Proper transaction handling

### 4. User Approval (REQUIRED)
**STOP and ask the user** before committing.

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example upsert SQL structure</summary>

```sql
-- Example pseudocode for upsert with confidence comparison
INSERT INTO review_candidates (...)
SELECT ... FROM UNNEST(...)
ON CONFLICT (filing_id, source_segment_id, char_position, suggested_metric_id)
DO UPDATE SET
    -- Only update if new confidence > existing
    suggestion_confidence = CASE
        WHEN EXCLUDED.suggestion_confidence > review_candidates.suggestion_confidence
        THEN EXCLUDED.suggestion_confidence
        ELSE review_candidates.suggestion_confidence
    END,
    triggering_keyword = CASE
        WHEN EXCLUDED.suggestion_confidence > review_candidates.suggestion_confidence
        THEN EXCLUDED.triggering_keyword
        ELSE review_candidates.triggering_keyword
    END,
    updated_at = CASE
        WHEN EXCLUDED.suggestion_confidence > review_candidates.suggestion_confidence
        THEN now()
        ELSE review_candidates.updated_at
    END
WHERE EXCLUDED.suggestion_confidence > review_candidates.suggestion_confidence
RETURNING candidate_id, (xmax = 0) AS was_inserted;
```
</details>

## Reference

- **Issue source**: Slack filing duplicate candidates analysis
- **Dependencies**: DUP-1 (schema migration)
- **Related**: DUP-3 (deduplicator integration)

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

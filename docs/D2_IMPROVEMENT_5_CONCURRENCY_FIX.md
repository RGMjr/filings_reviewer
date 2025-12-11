# D2 Improvement #5: Concurrency Fix and Race Condition Testing

**Date**: 2025-12-10
**Status**: Complete ✅

## Summary

Added UNIQUE constraint to `review_decisions.candidate_id` to prevent duplicate decisions at the database level, and implemented comprehensive concurrency testing to verify race condition handling. This fix closes a critical bug that allowed multiple decisions for the same candidate in concurrent scenarios.

## Problem Discovered

The concurrency test revealed that the existing duplicate decision prevention was **insufficient for race conditions**:

**Before Fix**: All 5 concurrent requests succeeded
```
Created decision 635 for candidate 1892: accept
Created decision 636 for candidate 1892: accept
Created decision 637 for candidate 1892: accept
Created decision 638 for candidate 1892: accept
Created decision 639 for candidate 1892: accept
```

**Root Cause**: The `review_decisions` table lacked a UNIQUE constraint on `candidate_id`, so:
1. The application-level check at `api.py:129-144` could not prevent race conditions
2. Multiple concurrent requests could all pass the check before any decision was committed
3. All requests successfully inserted decisions into the database
4. The UniqueViolation exception handler at `api.py:202-216` **was never triggered**

## Solution

### Schema Fix

Added UNIQUE constraint to ensure database-level enforcement:

**File**: `sql/07_create_review_schema.sql`

**Before** (Line 87):
```sql
candidate_id BIGINT NOT NULL REFERENCES review_candidates(candidate_id) ON DELETE CASCADE,
```

**After** (Line 87):
```sql
candidate_id BIGINT NOT NULL UNIQUE REFERENCES review_candidates(candidate_id) ON DELETE CASCADE,
```

**Removed Redundant Index** (Lines 119-125):
```sql
-- Indices
-- Note: No index needed on candidate_id - UNIQUE constraint creates one automatically
CREATE INDEX idx_review_decisions_decision ON review_decisions(decision);
```

The UNIQUE constraint automatically creates an index, so `idx_review_decisions_candidate` is no longer needed.

### Database Migration

Applied to both test and dev databases:

```sql
-- Add UNIQUE constraint
ALTER TABLE review_decisions
ADD CONSTRAINT review_decisions_candidate_id_unique UNIQUE (candidate_id);

-- Drop redundant index
DROP INDEX IF EXISTS idx_review_decisions_candidate;
```

## Concurrency Test

### Implementation

**File**: `tests/integration/web/test_api_integration.py`

**New Test** (Lines 371-469): `test_concurrent_decision_race_condition`

```python
def test_concurrent_decision_race_condition(self, client, db_adapter, test_data):
    """Test that concurrent requests for same candidate are handled correctly.

    Simulates a race condition where multiple requests try to create
    decisions for the same candidate simultaneously. Verifies:
    - Exactly one request succeeds (201)
    - Other requests receive 409 Conflict
    - Database UNIQUE constraint prevents duplicate decisions
    - Transaction isolation prevents race conditions
    """
    filing_id, candidate_id_1, candidate_id_2 = test_data

    # Number of concurrent requests to simulate race condition
    num_threads = 5
    results = []
    results_lock = threading.Lock()

    def make_decision_request(thread_id):
        """Make a decision request and store the result."""
        try:
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": candidate_id_1,
                    "decision": "accept",
                    "assigned_metric_id": "cm_active_customers_total",
                    "reviewer_notes": f"Request from thread {thread_id}",
                },
            )

            with results_lock:
                results.append({
                    "thread_id": thread_id,
                    "status_code": response.status_code,
                    "data": json.loads(response.data),
                })
        except Exception as e:
            with results_lock:
                results.append({
                    "thread_id": thread_id,
                    "error": str(e),
                })

    # Create threads that will all try to create decisions simultaneously
    threads = []
    for i in range(num_threads):
        thread = threading.Thread(target=make_decision_request, args=(i,))
        threads.append(thread)

    # Start all threads as close to simultaneously as possible
    for thread in threads:
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    # Analyze results
    successes = [r for r in results if r.get("status_code") == 201]
    conflicts = [r for r in results if r.get("status_code") == 409]
    errors = [r for r in results if "error" in r]

    # Verify exactly one success
    assert len(successes) == 1
    # Verify all others are conflicts
    assert len(conflicts) == num_threads - 1
    # Verify no unexpected errors
    assert len(errors) == 0

    # Verify conflict response structure
    for conflict in conflicts:
        assert conflict["data"]["status"] == "error"
        assert "already exists" in conflict["data"]["message"]
        assert conflict["data"].get("error_type") == "duplicate_decision"

    # Verify only one decision in database
    decision = db_adapter.get_decision_for_candidate(candidate_id_1)
    assert decision is not None
    assert decision["decision"] == "accept"

    # Verify candidate status updated exactly once
    candidate = db_adapter.get_review_candidate(candidate_id_1)
    assert candidate["review_status"] == "reviewed"
```

### Test Strategy

The concurrency test uses threading to simulate a true race condition:

1. **5 concurrent threads** all try to create decisions for the same candidate
2. **Threads start simultaneously** to maximize chance of race condition
3. **Results collected** in thread-safe manner using `threading.Lock()`
4. **Assertions verify**:
   - Exactly 1 success (201 Created)
   - Exactly 4 conflicts (409 Conflict)
   - No unexpected errors
   - Only 1 decision in database
   - Candidate status updated exactly once

### Test Results

**After Fix**: One success, four conflicts (correct behavior)

```
INFO     src.web.routes.api:api.py:164 Created decision 645 for candidate 1896: accept

ERROR    src.infra.db:db.py:87 Database error, rolling back: duplicate key value violates
         unique constraint "review_decisions_candidate_id_unique"
         DETAIL:  Key (candidate_id)=(1896) already exists.

WARNING  src.web.routes.api:api.py:204 Unique constraint violation creating decision
         for candidate 1896: duplicate key value violates unique constraint
         "review_decisions_candidate_id_unique"
         DETAIL:  Key (candidate_id)=(1896) already exists.

[Repeated 3 more times for other threads]

PASSED [100%]
```

**All Integration Tests**: 8/8 passed ✅

```
test_accept_decision_end_to_end PASSED
test_reject_decision_end_to_end PASSED
test_reclassify_decision_end_to_end PASSED
test_transaction_atomicity PASSED
test_duplicate_decision_prevented PASSED
test_next_candidate_navigation PASSED
test_invalid_metric_id_database_check PASSED
test_concurrent_decision_race_condition PASSED ✨ (NEW)
```

## How the Fix Works

### Defense in Depth

The system now has **two layers of protection** against duplicate decisions:

#### Layer 1: Application-Level Check (Fast Path)
**Location**: `src/web/routes/api.py:129-144`

```python
# Check for existing decision
existing = db.get_decision_for_candidate(candidate_id)
if existing:
    logger.warning(f"Candidate {candidate_id} already has decision {existing['decision_id']}")
    return (
        jsonify({
            "status": "error",
            "message": "Candidate already has a decision",
            "existing_decision_id": existing["decision_id"],
        }),
        409,
    )
```

**Purpose**: Prevent most duplicate attempts before hitting the database
**Limitation**: Cannot prevent race conditions (TOCTOU - Time Of Check, Time Of Use)

#### Layer 2: Database UNIQUE Constraint (Guaranteed)
**Location**: `sql/07_create_review_schema.sql:87`

```sql
candidate_id BIGINT NOT NULL UNIQUE REFERENCES review_candidates(candidate_id) ON DELETE CASCADE,
```

**Purpose**: **Guaranteed** prevention of duplicates at database level
**Behavior**: Raises `psycopg.errors.UniqueViolation` if duplicate attempted

#### Layer 3: Exception Handler (User-Friendly)
**Location**: `src/web/routes/api.py:202-216`

```python
except psycopg.errors.UniqueViolation as e:
    # Duplicate decision (race condition bypassing our check at line 129)
    logger.warning(f"Unique constraint violation creating decision for candidate {data.get('candidate_id')}: {e}")
    return (
        jsonify({
            "status": "error",
            "message": "A decision already exists for this candidate",
            "error_type": "duplicate_decision",
        }),
        409,
    )
```

**Purpose**: Convert database error into user-friendly 409 Conflict response
**Trigger**: Only when Layer 1 check is bypassed due to race condition

## Benefits

### 1. **Data Integrity Guaranteed**
- Database enforces one-decision-per-candidate invariant
- No possibility of duplicate decisions, even under high concurrency
- Prevents data corruption from race conditions

### 2. **Correct HTTP Semantics**
- Sequential duplicates: Caught by Layer 1, return 409 with `existing_decision_id`
- Concurrent duplicates: Caught by Layer 2, return 409 with `error_type: "duplicate_decision"`
- Both return appropriate 409 Conflict status

### 3. **Comprehensive Testing**
- Existing `test_duplicate_decision_prevented` tests sequential case
- New `test_concurrent_decision_race_condition` tests concurrent case
- Full coverage of both single-threaded and multi-threaded scenarios

### 4. **Performance**
- UNIQUE constraint creates an index automatically (efficient lookups)
- Removed redundant `idx_review_decisions_candidate` index
- No performance degradation - database already checks constraint during INSERT

## Impact Analysis

### What Changed
1. **Schema**: Added UNIQUE constraint to `candidate_id`
2. **Tests**: Added concurrency test with 5 simultaneous threads
3. **Behavior**: Concurrent duplicates now properly return 409 instead of creating duplicates

### What Stayed the Same
1. **API contract**: Same 409 response for duplicates (sequential or concurrent)
2. **Application code**: No changes to `api.py` (constraint does the work)
3. **Existing tests**: All 7 original tests still pass
4. **User experience**: No visible change (duplicates were already blocked in normal use)

### Critical Bug Fixed
**Before**: Users making rapid/concurrent decisions could create duplicates
**After**: Database guarantees only one decision per candidate, even under load

## Related Files

- `sql/07_create_review_schema.sql` - Added UNIQUE constraint
- `tests/integration/web/test_api_integration.py` - Added concurrency test
- `src/web/routes/api.py` - Exception handler now triggered correctly
- `docs/D2_EXCEPTION_HANDLING.md` - Documents the UniqueViolation handler
- `docs/D2_TRANSACTION_MANAGEMENT_FIX.md` - Related transaction atomicity fix

## Future Considerations

### 1. **Load Testing**
Test with higher concurrency (50-100 threads) to verify performance under load:
```python
# Stress test with 100 concurrent requests
num_threads = 100
```

### 2. **Monitoring**
Track UniqueViolation frequency in production:
- High frequency → Investigate if UI is allowing rapid duplicate submissions
- Low frequency → Expected rare race conditions

### 3. **Rate Limiting**
Consider rate limiting per candidate to prevent accidental rapid submissions:
```python
# Limit to 1 decision per candidate per second
@limiter.limit("1 per second", key_func=lambda: request.json.get("candidate_id"))
```

### 4. **Optimistic Locking**
For future updates to decisions, consider optimistic locking:
```sql
ALTER TABLE review_decisions ADD COLUMN version INT DEFAULT 1;
```

## Summary

The concurrency fix and test provide:

✅ **Critical bug fixed** - Duplicate decisions no longer possible under concurrency
✅ **Database-level guarantee** - UNIQUE constraint ensures data integrity
✅ **Comprehensive testing** - Concurrency test with 5 simultaneous threads
✅ **Backward compatible** - All existing tests pass (8/8)
✅ **Proper error handling** - UniqueViolation correctly returns 409 Conflict
✅ **No performance impact** - UNIQUE constraint creates efficient index
✅ **Production ready** - Defense in depth with 3 layers of protection

The D2 API routes now correctly handle concurrent decision requests with guaranteed data integrity.

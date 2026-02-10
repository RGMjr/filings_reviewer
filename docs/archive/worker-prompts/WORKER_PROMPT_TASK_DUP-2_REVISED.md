# WORKER PROMPT: Task DUP-2 (Revised) - Upsert Logic and Suppression Logging

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       DUP-2
TASK NAME:     Add upsert logic to bulk_insert_review_candidates with runner-up capture
WORKSTREAM:    Human Review System Improvements
SOURCE:        Slack filing duplicate candidates analysis + critical evaluation
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 5-6 hours (algorithm design 1h, implementation 2.5h, testing 2h)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (modifies core database adapter method)
TASK SIZE:     L
DEPENDS ON:    DUP-1 (Database Schema Migration) ✅ COMPLETE
UNLOCKS:       DUP-3 (Deduplicator Helpers Integration), UXI-ALT (Alternative Metric UI)
BLOCKS:        DUP-3
PARALLEL WITH: None
REVISION:      2.0 (addresses partial index issues, return contract, runner-up capture)
═══════════════════════════════════════════════════════════════════════════════
```

## Revision Summary

This revision addresses blockers identified in critical evaluation:

| Issue | Original Spec | Revised Spec |
|-------|---------------|--------------|
| Partial index compatibility | Single `ON CONFLICT` | Two-phase: pre-fetch + conditional logic |
| Return contract | Variable length | **Fixed length**: one ID per input, in order |
| Capturing OLD values | RETURNING (doesn't work) | Pre-fetch existing before update |
| Return type inconsistency | Mixed `int` / `list[dict]` | Canonical: `tuple[list[int], list[dict]]` |
| Runner-up capture | Not specified | **New**: best alternative metric logged |

---

## Objective

Modify `bulk_insert_review_candidates()` to:

1. **Handle conflicts idempotently** - Re-running candidate generation produces same result
2. **Keep highest confidence** - Winner determined by `suggestion_confidence`
3. **Preserve return contract** - Return one `candidate_id` per input, in input order
4. **Capture runner-up** - Best alternative metric stored for UI quick-select

### Business Rationale

- **Idempotency**: Running candidate generation twice shouldn't create duplicates
- **Quality**: Higher confidence candidates should win conflicts
- **UX**: Show reviewer "we suggested X, but also considered Y" for faster reclassification

---

## Uniqueness Keys (from DUP-1)

Two partial unique indexes exist on `review_candidates`:

```sql
-- Candidates WITH source_segment_id (most common)
UNIQUE (filing_id, source_segment_id, char_position, suggested_metric_id)
WHERE source_segment_id IS NOT NULL

-- Candidates WITHOUT source_segment_id
UNIQUE (filing_id, char_position, suggested_metric_id)
WHERE source_segment_id IS NULL
```

**Key insight**: `suggested_metric_id` is part of the uniqueness key. Two candidates at the same position with different metrics are NOT conflicts—they can coexist.

### Position Key (for runner-up)

For runner-up purposes, we use **position only** (excluding metric):

```python
# Position key (for grouping alternatives)
position_key = (filing_id, source_segment_id, char_position)

# Uniqueness key (for conflict detection)
uniqueness_key = (filing_id, source_segment_id, char_position, suggested_metric_id)
```

---

## Algorithm: Two-Phase Conflict Handling

### Phase 1: Conflict Detection and Resolution

```
INPUT: candidates[] - list of candidate dicts to insert
OUTPUT: (candidate_ids[], suppression_logs[])

1. VALIDATE all candidates (fail fast)

2. GROUP candidates by uniqueness_key
   - If multiple candidates have same uniqueness_key, keep highest confidence
   - Log others with reason='lower_confidence' (within-batch dedup)

3. SPLIT remaining candidates by source_segment_id IS NULL vs NOT NULL
   - This avoids partial index issues

4. For each split group:
   a. BUILD uniqueness keys for the batch
   b. QUERY existing candidates matching those keys
   c. For each candidate:
      - If NO existing: mark for INSERT
      - If existing.confidence < new.confidence: mark for UPDATE, log existing as suppressed
      - If existing.confidence >= new.confidence: mark as SKIPPED, log new as suppressed
      - Record the final candidate_id (new or existing)

5. EXECUTE batch INSERT for new candidates
6. EXECUTE batch UPDATE for winners replacing existing
7. BUILD result: candidate_ids in input order (new IDs for inserts, existing IDs for skips)
```

### Phase 2: Runner-Up Capture

```
8. GROUP all input candidates by position_key (excluding metric_id)

9. For each position with multiple metric suggestions:
   a. Identify WINNER: the candidate that ended up in review_candidates
   b. Identify RUNNER-UP: highest confidence candidate with DIFFERENT metric_id
   c. If runner-up exists and differs from winner: log with reason='runner_up'

10. EXECUTE bulk insert of all suppression logs

11. RETURN (candidate_ids, suppression_logs)
```

---

## Function Contract

### Signature

```python
def bulk_insert_review_candidates(
    self,
    candidates: list[dict[str, Any]],
    *,
    log_suppressed: bool = False,
) -> list[int] | tuple[list[int], list[dict[str, Any]]]:
    """
    Bulk insert review candidates with conflict resolution.

    Handles conflicts by keeping higher-confidence candidates. When
    log_suppressed=True, also captures suppressed alternatives and
    runner-ups for UI display.

    Args:
        candidates: List of candidate dicts. Required keys:
            - filing_id, company_id, char_position, context_text
            - raw_number_text, triggering_keyword, keyword_distance
            - keyword_position
          Optional keys:
            - source_segment_id, parsed_value, parsed_unit
            - suggested_metric_id, suggestion_confidence, features
            - review_batch_id

        log_suppressed: If True, log suppressed candidates to
            suppressed_candidates table and return detailed info.

    Returns:
        If log_suppressed=False (default):
            list[int] - candidate_ids, one per input, in input order.
                       For conflicts where input loses, returns winner's ID.

        If log_suppressed=True:
            tuple[list[int], list[dict]] where:
                - list[int]: candidate_ids as above
                - list[dict]: suppression log entries with keys:
                    - suppressed_id: ID in suppressed_candidates table
                    - winner_candidate_id: ID of winning candidate
                    - suppression_reason: 'lower_confidence' | 'runner_up'
                    - input_index: index in original candidates list (or None)

    Guarantees:
        - len(returned_ids) == len(candidates) ALWAYS
        - returned_ids[i] is the candidate_id for candidates[i]
        - Order preserved: zip(candidates, returned_ids, strict=True) is safe

    Raises:
        ValidationError: If any candidate has invalid keyword_position
        ValidationError: If any candidate has invalid suggestion_confidence
    """
```

### Return Value Examples

```python
# Input: 3 candidates
candidates = [
    {"char_position": 100, "suggested_metric_id": "cm_arr", "suggestion_confidence": 0.8, ...},
    {"char_position": 100, "suggested_metric_id": "cm_arr", "suggestion_confidence": 0.9, ...},  # wins
    {"char_position": 100, "suggested_metric_id": "cm_mrr", "suggestion_confidence": 0.7, ...},  # runner-up
]

# With log_suppressed=False
ids = db.bulk_insert_review_candidates(candidates)
# ids = [42, 42, 43]
#        ^   ^   ^
#        |   |   +-- cm_mrr inserted as ID 43
#        |   +------ cm_arr winner inserted as ID 42
#        +---------- cm_arr loser gets winner's ID 42

# With log_suppressed=True
ids, logs = db.bulk_insert_review_candidates(candidates, log_suppressed=True)
# ids = [42, 42, 43]
# logs = [
#     {"suppressed_id": 1, "winner_candidate_id": 42, "suppression_reason": "lower_confidence", "input_index": 0},
#     {"suppressed_id": 2, "winner_candidate_id": 42, "suppression_reason": "runner_up", "input_index": 2},
# ]
```

---

## Suppression Reasons

Update the `check_suppression_reason` constraint to include `runner_up`:

```sql
-- Migration addition (run before implementation)
ALTER TABLE suppressed_candidates
DROP CONSTRAINT check_suppression_reason;

ALTER TABLE suppressed_candidates
ADD CONSTRAINT check_suppression_reason
CHECK (suppression_reason IN (
    'lower_confidence',    -- Lost confidence comparison at same uniqueness key
    'cross_sentence',      -- Same-sentence match preferred (future use)
    'duplicate_execution', -- Candidate gen was run twice (future use)
    'runner_up'            -- Best alternative metric for position (for UI)
));
```

### Suppression Log Entry Schema

```python
{
    # Identifiers
    "suppressed_id": int,           # PK in suppressed_candidates
    "winner_candidate_id": int,     # FK to review_candidates

    # Reason
    "suppression_reason": str,      # 'lower_confidence' | 'runner_up'

    # Context (for debugging/analysis)
    "input_index": int | None,      # Index in input list (None if from DB)
    "winner_confidence": float,     # Winner's confidence at suppression time
    "suppressed_confidence": float, # Suppressed candidate's confidence
    "suggested_metric_id": str,     # Metric ID of suppressed candidate
}
```

---

## Tie Handling

When two candidates have **identical confidence**:

1. **Existing wins**: If conflict with DB, existing row is kept
2. **First wins**: If conflict within batch, first in input order wins
3. **Runner-up still captured**: The loser is logged as `runner_up` if it has a different metric

```python
# Example: tie at same position, same metric
candidate_a = {"confidence": 0.8, "metric": "cm_arr", ...}  # first in list
candidate_b = {"confidence": 0.8, "metric": "cm_arr", ...}  # second in list

# Result: candidate_a wins (first-wins), candidate_b logged as lower_confidence
```

---

## Files to Modify

### 1. `sql/08_add_suppressed_candidates.sql` (or new migration)

Add `runner_up` to suppression_reason constraint.

### 2. `src/infra/db.py`

- Modify `bulk_insert_review_candidates()` with two-phase algorithm
- Add helper: `_fetch_conflicting_candidates(uniqueness_keys, has_segment: bool)`
- Add helper: `_bulk_log_suppressed(suppression_entries: list[dict])`

---

## Files to Read (Context)

- `src/infra/db.py` lines 1072-1218 (current implementation)
- `src/review/helpers.py` lines 150-171 (caller with zip strict=True)
- `sql/08_add_suppressed_candidates.sql` (table schema)
- `src/review/models.py` (ReviewCandidate model)

---

## Implementation Steps

### Step 1: Update Constraint (SQL)

```sql
-- Add runner_up reason
ALTER TABLE suppressed_candidates
DROP CONSTRAINT IF EXISTS check_suppression_reason;

ALTER TABLE suppressed_candidates
ADD CONSTRAINT check_suppression_reason
CHECK (suppression_reason IN (
    'lower_confidence', 'cross_sentence', 'duplicate_execution', 'runner_up'
));
```

### Step 2: Add Helper Methods

```python
def _fetch_conflicting_candidates(
    self,
    uniqueness_keys: list[tuple],
    has_segment: bool,
) -> dict[tuple, dict[str, Any]]:
    """
    Fetch existing candidates that would conflict with the given keys.

    Args:
        uniqueness_keys: List of (filing_id, segment_id, char_pos, metric_id) tuples
        has_segment: If True, use segment-aware index; if False, use segment-null index

    Returns:
        Dict mapping uniqueness_key -> existing candidate row dict
    """


def _bulk_log_suppressed(
    self,
    entries: list[dict[str, Any]],
) -> list[int]:
    """
    Bulk insert suppressed candidate records.

    Args:
        entries: List of dicts with all suppressed_candidates columns

    Returns:
        List of suppressed_id values
    """
```

### Step 3: Implement Two-Phase Algorithm

See Algorithm section above. Key implementation notes:

1. **Split by segment NULL**: Process `source_segment_id IS NOT NULL` and `IS NULL` candidates separately
2. **Batch queries**: Use `WHERE (filing_id, segment_id, char_pos, metric_id) IN (...)` for efficiency
3. **Preserve order**: Use dict to track `input_index -> final_candidate_id` mapping
4. **Transaction**: All operations in single transaction for atomicity

### Step 4: Runner-Up Detection

```python
def _identify_runner_ups(
    self,
    candidates: list[dict],
    final_ids: list[int],
) -> list[dict]:
    """
    Identify runner-up candidates for each position.

    Groups by position_key (filing_id, segment_id, char_position).
    For each position with multiple metric suggestions, finds the
    best alternative to the winner.

    Returns:
        List of suppression entries for runner-ups
    """
```

---

## Test Requirements

### Coverage Target: **≥ 90%** for new/modified methods

### Test File: `tests/unit/infra/test_db_upsert.py`

### Test Cases (18+ tests)

#### 1. Basic Insert (3 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_insert_single_new` | 1 new candidate | Returns [new_id], no suppressions |
| `test_insert_multiple_new` | 3 new candidates, no conflicts | Returns [id1, id2, id3] |
| `test_insert_empty_list` | [] | Returns [], no DB calls |

#### 2. Conflict: New Loses (3 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_conflict_new_lower_confidence` | New conf=0.5, existing conf=0.8 | Returns [existing_id], logs new as suppressed |
| `test_conflict_new_equal_confidence` | New conf=0.8, existing conf=0.8 | Returns [existing_id], logs new (existing wins tie) |
| `test_conflict_multiple_losers` | 3 candidates, all lose to existing | Returns [ex1, ex2, ex3], logs all 3 |

#### 3. Conflict: New Wins (3 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_conflict_new_higher_confidence` | New conf=0.9, existing conf=0.5 | Returns [existing_id], existing row updated, old logged |
| `test_conflict_winner_replaces_existing` | Verify UPDATE happened | Check DB has new values |
| `test_conflict_old_values_captured` | Check suppression log | Log contains OLD confidence, OLD metric |

#### 4. Runner-Up Capture (4 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_runner_up_captured` | 2 candidates same position, different metrics | Winner inserted, runner-up logged |
| `test_runner_up_different_metric_only` | 2 candidates same position+metric | Only lower_confidence, no runner_up |
| `test_runner_up_highest_alternative` | 3 metrics at same position | Runner-up is 2nd highest different metric |
| `test_runner_up_linked_to_winner` | Verify FK | suppressed.winner_candidate_id = winner's ID |

#### 5. NULL Segment Handling (3 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_null_segment_conflict` | Two candidates with NULL segment_id, same position+metric | Conflict resolved correctly |
| `test_mixed_null_and_not_null` | Batch with both NULL and non-NULL | Processed separately, both correct |
| `test_null_segment_runner_up` | Runner-up with NULL segment | Captured correctly |

#### 6. Return Contract (2 tests)

| Test | Input | Expected |
|------|-------|----------|
| `test_return_length_matches_input` | N candidates with various outcomes | len(result) == N |
| `test_return_order_preserved` | Specific order with conflicts | zip(input, output, strict=True) works |

---

## Acceptance Criteria

- [ ] `bulk_insert_review_candidates()` uses two-phase conflict resolution
- [ ] Return value length ALWAYS equals input length
- [ ] Return value order matches input order
- [ ] Higher-confidence candidates win conflicts
- [ ] Existing row wins ties (equal confidence)
- [ ] Suppressed candidates logged with correct reason
- [ ] Runner-up captured for positions with multiple metrics
- [ ] Runner-up has different `suggested_metric_id` than winner
- [ ] NULL `source_segment_id` handled correctly (separate from non-NULL)
- [ ] `suppression_reason` constraint updated to include 'runner_up'
- [ ] Backward compatible: `log_suppressed=False` returns `list[int]` only
- [ ] **18+ unit tests** covering all scenarios
- [ ] **Test coverage ≥ 90%** for modified methods
- [ ] All existing tests still pass
- [ ] `helpers.py` caller works unchanged

---

## Do NOT

- Use single `ON CONFLICT` spanning both partial indexes
- Return fewer IDs than input candidates
- Change return order vs input order
- Add new dependencies
- Modify table schemas beyond constraint update
- Break existing callers using default parameters

---

## Verification Commands

```bash
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer

# Update constraint first
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
ALTER TABLE suppressed_candidates DROP CONSTRAINT IF EXISTS check_suppression_reason;
ALTER TABLE suppressed_candidates ADD CONSTRAINT check_suppression_reason
CHECK (suppression_reason IN ('lower_confidence', 'cross_sentence', 'duplicate_execution', 'runner_up'));
"

# Also update test DB
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test -c "
ALTER TABLE suppressed_candidates DROP CONSTRAINT IF EXISTS check_suppression_reason;
ALTER TABLE suppressed_candidates ADD CONSTRAINT check_suppression_reason
CHECK (suppression_reason IN ('lower_confidence', 'cross_sentence', 'duplicate_execution', 'runner_up'));
"

# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_upsert.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_upsert.py \
  --cov=src/infra/db --cov-report=term-missing

# Verify existing tests still pass
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_db_review_methods.py -v --tb=short

# Verify helpers.py caller works
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_helpers.py -v --tb=short
```

---

## Follow-On Task: UXI-ALT (Alternative Metric UI)

After DUP-2 completion, create task for:

1. **Show alternative in review UI**:
   - Query `suppressed_candidates WHERE winner_candidate_id = ? AND suppression_reason = 'runner_up'`
   - Display: "Alternative: {metric_name} ({confidence}%)"

2. **One-click switch**:
   - In "Reclassify" flow, show runner-up as first option
   - Click to pre-fill reclassification form

3. **Search fallback**:
   - If no runner-up exists, show full metric search

---

## Reference

- **Original issue**: Slack filing duplicate candidates
- **Critical evaluation**: Partial index issues, return contract, SQL syntax
- **Dependencies**: DUP-1 (schema) ✅
- **Unlocks**: DUP-3 (deduplicator), UXI-ALT (UI)

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
**Revision**: 2.0

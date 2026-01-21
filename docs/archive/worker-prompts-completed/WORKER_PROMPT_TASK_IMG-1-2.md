# WORKER PROMPT: Task IMG-1-2 - Database Methods for Image Review

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-2
TASK NAME:     Add CRUD methods to DatabaseAdapter for image review
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours (implementation 1.5hr, tests 1hr)
RISK LEVEL:    Low (additive methods, no existing code modified)
TASK SIZE:     M
DEPENDS ON:    IMG-1-1
UNLOCKS:       IMG-1-3, IMG-1-4, IMG-1-5
BLOCKS:        IMG-1-3, IMG-1-4, IMG-1-5, IMG-1-6, IMG-1-7, IMG-1-8
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add database methods to `DatabaseAdapter` for CRUD operations on image review candidates and decisions. These methods power the image review UI and candidate generation script.

**Business Rationale**: Clean database abstraction enables the web UI (IMG-1-4, IMG-1-5) and scripts (IMG-1-3) to interact with image review data without raw SQL.

**Current Behavior**: No methods exist for image review tables.

**Desired Behavior**: DatabaseAdapter has methods for listing, creating, updating, and querying image candidates and decisions.

## Prerequisites

- IMG-1-1 complete (database schema exists)
- Understand existing review methods in `src/infra/db.py`

## Files to Modify

1. **`src/infra/db.py`** - Add image review methods to DatabaseAdapter class

## Files to Create

1. **`tests/unit/infra/test_db_image_methods.py`** - Unit tests for new methods

## Files to Read (Context Only)

- `src/infra/db.py` - Existing DatabaseAdapter patterns (especially review methods)
- `sql/09_create_image_review_schema.sql` - Table structure
- `tests/unit/infra/test_db.py` or `tests/integration/test_db_review_methods.py` - Test patterns

## Implementation Requirements

### Core Functionality

1. **`get_filings_with_image_candidates(status, limit, offset)`**
   - Returns list of filings that have image candidates
   - Filter by review_status ('pending', 'reviewed', 'all')
   - Include counts: total_candidates, pending_count, reviewed_count
   - Pagination support
   - Order by pending_count DESC (prioritize filings with work)

2. **`get_image_review_candidates_for_filing(filing_id, status, sort_by, limit, offset)`**
   - Returns candidates for a specific filing
   - Filter by review_status
   - Sort options: 'tier' (detection_tier priority), 'confidence', 'position'
   - Include decision data if exists (LEFT JOIN)
   - Pagination support

3. **`get_image_review_candidate(image_candidate_id)`**
   - Returns single candidate with all metadata
   - Include filing info (company_name, accession_number)
   - Include decision if exists

4. **`get_next_pending_image_candidate(filing_id, current_candidate_id)`**
   - Returns next pending candidate after current one
   - Order by detection_tier priority, then cohort_confidence DESC
   - Returns None if no more pending

5. **`insert_image_review_candidate(candidate_data)`**
   - Insert new candidate from inventory data
   - Upsert on (filing_id, image_src) unique constraint
   - Return candidate_id

6. **`insert_image_review_decision(image_candidate_id, decision, chart_type, rejection_reason, reviewer_id, reviewer_notes, review_time_seconds)`**
   - Insert decision and update candidate status to 'reviewed'
   - Validate: chart_type required if decision='relevant'
   - Validate: rejection_reason required if decision='not_relevant'
   - Return decision_id and next_candidate info

7. **`delete_image_review_decision(image_decision_id)`**
   - Delete decision and reset candidate status to 'pending'
   - Return success boolean

8. **`update_image_candidate_status(image_candidate_id, status)`**
   - Update review_status ('pending', 'reviewed', 'skipped')

9. **`get_image_review_progress()`**
   - Returns aggregate stats: total_candidates, reviewed, pending, by_tier breakdown
   - Used for dashboard/progress display

10. **`get_image_decision_statistics()`**
    - Returns decision distribution by tier (for pattern learning)
    - Columns: detection_tier, relevant_count, not_relevant_count, precision_pct

### Detection Tier Priority Order

```python
TIER_PRIORITY = {
    'tier_1_cohort': 1,
    'tier_2_large': 2,
    'tier_3_all': 3,
    'seed_list': 0,  # Highest priority
}
```

### Error Handling

- Raise `ValueError` for invalid status/sort_by values
- Return `None` for get_* methods when not found
- Use transactions for insert_decision (decision + status update)

## Test Requirements

### Coverage Target: **≥ 90%** for new methods

### Test Categories (15+ tests recommended)

1. **Candidate Query Tests** (5-6 tests)
   - get_filings_with_image_candidates returns correct counts
   - get_image_review_candidates_for_filing filters by status
   - get_image_review_candidates_for_filing sorts by tier priority
   - get_next_pending_image_candidate returns correct next
   - get_next_pending_image_candidate returns None when exhausted

2. **Decision CRUD Tests** (5-6 tests)
   - insert_image_review_decision creates decision
   - insert_image_review_decision updates candidate status
   - insert_image_review_decision validates chart_type requirement
   - insert_image_review_decision validates rejection_reason requirement
   - delete_image_review_decision resets candidate status

3. **Statistics Tests** (3-4 tests)
   - get_image_review_progress returns correct totals
   - get_image_decision_statistics groups by tier
   - Handles empty tables gracefully

### Known Edge Cases to Test

- Filing with no image candidates
- Candidate with no decision (pending)
- All candidates reviewed (no next)
- Decision undo when candidate was skipped

## Acceptance Criteria

- [ ] All 10 methods implemented in DatabaseAdapter
- [ ] Methods follow existing code patterns (parameter style, return types)
- [ ] **15+ unit tests** covering all methods
- [ ] **Test coverage ≥ 90%** for new methods
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] Type hints on all new methods
- [ ] Docstrings on all public methods
- [ ] NO changes to existing review methods (text-based)

## Do NOT

- Modify existing review methods (get_review_candidates, insert_review_decision, etc.)
- Add Flask routes (that's IMG-1-4, IMG-1-5)
- Create the candidate generation script (that's IMG-1-3)
- Change database schema (that's IMG-1-1)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_image_methods.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/test_db_image_methods.py \
  --cov=src.infra.db --cov-report=term-missing

# Verify no regressions in existing db tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/infra/ tests/integration/test_db_review_methods.py --no-cov -q

# Type check (if db.py has type hints)
mypy src/infra/db.py --ignore-missing-imports
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing db methods**: `src/infra/db.py`
- **Dependencies**: IMG-1-1 (schema)
- **Related**: IMG-1-3, IMG-1-4, IMG-1-5 (consumers of these methods)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6

---

## Post-Completion Note (IMG-1-5)

**Added 2026-01-13**: The `get_image_decision_by_id(image_decision_id)` method was missing from the original requirements but was needed by IMG-1-5 (API routes) for the undo/delete endpoint. This method was added to `src/infra/db.py` as part of IMG-1-5 implementation, along with integration tests in `tests/integration/test_db_image_methods.py::TestGetImageDecisionById`.

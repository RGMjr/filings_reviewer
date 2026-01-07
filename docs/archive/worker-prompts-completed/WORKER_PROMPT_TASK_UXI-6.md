# WORKER PROMPT: Task UXI-6 - Bulk Action Limit Increase

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-6
TASK NAME:     Increase bulk action limit from 20 to 50 candidates
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-45 min (constant changes + test updates)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (configuration change only)
TASK SIZE:     XS
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-4, UXI-5
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Increase bulk action limit from 20 to 50 candidates.

**Business Rationale**: Filings with 100+ candidates are limited by 20-candidate bulk actions. Increasing to 50 reduces clicks for high-volume review sessions.

**Current Behavior**: Maximum 20 candidates per bulk action.

**Desired Behavior**: Maximum 50 candidates per bulk action.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/web/static/js/review.js`** - Update limit constant (2 locations)
2. **`src/web/routes/api.py`** - Update validation limit (1 location)
3. **`tests/unit/web/test_api_bulk.py`** - Update existing test for new limit

## Implementation Requirements

### Core Functionality

This is a simple constant change in 3 files:

1. **Client-side limit** (`review.js`):
   ```javascript
   // Line ~357 and ~391 - change both occurrences:
   - if (state.selectedCandidates.size > 20) {
   + if (state.selectedCandidates.size > 50) {
   ```

2. **Server-side limit** (`api.py`):
   ```python
   # Line ~745 - change the safety limit:
   - if len(candidate_ids) > 20:
   + if len(candidate_ids) > 50:
   ```

3. **Update alert message text** in both JS locations to say "Maximum 50 candidates"

4. **Update docstring** in `api.py` (line ~679) to reflect new limit

### No Chunking Required

PostgreSQL handles 50 inserts in a single transaction without issue. The existing `insert_bulk_review_decisions()` method already:
- Processes all candidates in one call
- Returns partial success with failed candidates list
- Handles errors gracefully

Adding chunking would introduce unnecessary complexity for this limit increase.

## Test Requirements

### Existing Test Coverage

The bulk endpoint already has comprehensive tests in `tests/unit/web/test_api_bulk.py`:
- Validation tests (empty, missing, invalid fields)
- Accept/reject functionality
- Edge cases (mixed filings, partial success, deduplication)

### Required Test Updates

1. **Update `test_over_20_candidates_returns_403`** → `test_over_50_candidates_returns_403`
   ```python
   def test_over_50_candidates_returns_403(self, client, mock_db):
       """More than 50 candidates should return 403."""
       candidate_ids = list(range(1, 52))  # 51 candidates
       # ... rest unchanged
       assert "Maximum 50 candidates" in data["message"]
   ```

2. **Add test for 50 candidates succeeds** (edge case at limit):
   ```python
   def test_exactly_50_candidates_succeeds(self, client, mock_db):
       """Exactly 50 candidates should succeed."""
       # Mock 50 candidates from same filing
       # Verify 200 response
   ```

## Acceptance Criteria

- [ ] Can select up to 50 candidates for bulk action in UI
- [ ] API accepts requests with up to 50 candidates
- [ ] API returns 403 for requests with >50 candidates
- [ ] Alert messages updated to say "Maximum 50 candidates"
- [ ] All existing bulk tests pass
- [ ] New limit test passes

## Do NOT

- Add chunking logic (not needed for 50 items)
- Add progress indicators (single API call completes quickly)
- Change partial failure handling (already works correctly)
- Modify bulk action UI layout
- Change single-candidate decision logic

## Verification Commands

```bash
# Run bulk API tests (dedicated test file)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_bulk.py -v

# Run with coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_bulk.py \
  --cov=src.web.routes.api --cov-report=term-missing

# Verify JS syntax (no runtime errors)
node --check src/web/static/js/review.js
```

## Critical Evaluation Phase

**Depth: Minimal (XS task)** - Simple constant change, verify tests pass.

## Reference

- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`
- **Related**: HRI-8 (Original bulk actions implementation)
- **Test file**: `tests/unit/web/test_api_bulk.py` (343 lines of existing coverage)

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
**Revision Note**: Simplified from original - removed unnecessary chunking complexity. PostgreSQL handles 50 inserts trivially.

# D2: API Routes Implementation Plan

## Overview

Create `src/web/routes/api.py` - JSON API endpoints for AJAX decision submission from the review interface.

**Dependencies:**
- ✅ A3: Database adapter methods (complete)
- ✅ C2: Flask app factory (complete)
- ✅ D1: Review routes (complete)

## Current State

### Existing Infrastructure

**Flask Application** (`src/web/app.py`):
- Lines 263-265: API blueprint registration is stubbed out
- Lines 268-274: `_wants_json_response()` helper for content negotiation
- Lines 277-291: Error handlers support JSON responses
- Lines 71-89: `get_db()` provides request-scoped database access

**Review Routes** (`src/web/routes/review.py`):
- D1 implementation complete with page routes
- Patterns to follow: validation, error handling, database access
- Helper functions: `_validate_positive_int()`, `_paginate()`

**Data Models** (`src/review/models.py`):
- Constants: `DECISION_TYPES`, `REJECTION_CATEGORIES`, `REVIEW_STATUSES`
- `CandidateFeatures.to_dict()` for JSONB serialization

**Database Adapter** (`src/infra/db.py`):
- Line 963: `insert_review_decision()` - Creates decision record
- Line 734: `update_candidate_status()` - Updates candidate status
- Line 559: `get_review_candidate()` - Fetches candidate by ID
- Line 1071: `get_decision_for_candidate()` - Fetches existing decision

### What's Missing

- **`src/web/routes/api.py`** - JSON API endpoints
- Blueprint registration in `app.py` (uncomment lines 264-265)
- Unit tests for API endpoints

## API Design

### Endpoint: `POST /api/decisions`

**Purpose:** Record a review decision (accept/reject/reclassify) via AJAX

**Request Body:**
```json
{
  "candidate_id": 123,
  "decision": "accept|reject|reclassify",
  "assigned_metric_id": "active_customers",  // Required for accept/reclassify
  "rejection_category": "wrong_metric",      // Required for reject
  "rejection_reason": "This is ARR, not CAC", // Optional for reject
  "reviewer_notes": "Checked source",        // Optional
  "review_time_seconds": 45                  // Optional, client-tracked
}
```

**Success Response (201 Created):**
```json
{
  "status": "success",
  "decision_id": 456,
  "candidate_id": 123,
  "next_candidate": {
    "candidate_id": 124,
    "url": "/review/5/candidate/124"
  }
}
```

**Error Response (400 Bad Request):**
```json
{
  "status": "error",
  "errors": {
    "assigned_metric_id": "Required for accept decision",
    "rejection_category": "Invalid category: 'wrong_metric_type'"
  }
}
```

**Error Response (404 Not Found):**
```json
{
  "status": "error",
  "message": "Candidate not found"
}
```

**Error Response (409 Conflict):**
```json
{
  "status": "error",
  "message": "Candidate already has a decision",
  "existing_decision_id": 789
}
```

### Endpoint: `GET /api/candidates/<int:candidate_id>`

**Purpose:** Get candidate details for dynamic loading (future enhancement)

**Success Response (200 OK):**
```json
{
  "status": "success",
  "candidate": {
    "candidate_id": 123,
    "filing_id": 5,
    "company_name": "Samsara Inc.",
    "context_text": "...",
    "raw_number_text": "100,000",
    "parsed_value": 100000,
    "suggested_metric_id": "active_customers",
    "review_status": "pending"
  }
}
```

### Endpoint: `GET /api/filings/<int:filing_id>/progress`

**Purpose:** Get review progress for a filing (future enhancement for live updates)

**Success Response (200 OK):**
```json
{
  "status": "success",
  "filing_id": 5,
  "total_candidates": 55,
  "pending_count": 30,
  "reviewed_count": 25,
  "review_pct": 45.5
}
```

## Implementation Steps

### Step 1: Create `src/web/routes/api.py`

**File Structure:**
```python
"""
JSON API endpoints for human review system.

Handles AJAX requests from the review interface for recording decisions
and fetching candidate data. All endpoints return JSON responses.
"""

import logging
from typing import Dict, List, Optional

from flask import Blueprint, jsonify, request
from src.review.models import (
    DECISION_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)
from src.web.app import get_db

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)

# =============================================================================
# Decision Recording
# =============================================================================

@api_bp.route("/decisions", methods=["POST"])
def create_decision():
    """Record a review decision (accept/reject/reclassify)."""
    # Implementation details below

# =============================================================================
# Candidate Retrieval (Future Enhancement)
# =============================================================================

@api_bp.route("/candidates/<int:candidate_id>", methods=["GET"])
def get_candidate(candidate_id: int):
    """Get candidate details."""
    # Future enhancement for dynamic loading

# =============================================================================
# Progress Tracking (Future Enhancement)
# =============================================================================

@api_bp.route("/filings/<int:filing_id>/progress", methods=["GET"])
def get_filing_progress(filing_id: int):
    """Get review progress for a filing."""
    # Future enhancement for live progress updates

# =============================================================================
# Helper Functions
# =============================================================================

def _validate_decision_request(data: Dict) -> Dict[str, List[str]]:
    """
    Validate decision request data.

    Returns:
        Dict of field_name -> list of error messages
        Empty dict if validation passes
    """
    # Validation logic
```

**Key Functions:**

1. **`create_decision()`** - Main endpoint
   - Parse and validate JSON request body
   - Check candidate exists and has no existing decision
   - Validate decision-specific fields (metric_id for accept, category for reject)
   - Begin database transaction
   - Insert decision record
   - Update candidate status to "reviewed"
   - Commit transaction
   - Fetch next pending candidate for same filing
   - Return success response with next candidate info

2. **`_validate_decision_request(data)`** - Validation helper
   - Required fields: `candidate_id`, `decision`
   - `decision` must be in DECISION_TYPES
   - If `decision == "accept"` or `"reclassify"`: require `assigned_metric_id`
   - If `decision == "reject"`: require `rejection_category` in REJECTION_CATEGORIES
   - Validate `review_time_seconds` is positive if provided
   - Return dict of errors (empty if valid)

3. **`_get_next_candidate_info(db, filing_id, current_id)`** - Navigation helper
   - Query for next pending candidate in same filing (candidate_id > current_id)
   - Return dict with candidate_id and URL, or None if no more pending

### Step 2: Update `src/web/app.py`

**Change:** Uncomment lines 264-265 to register API blueprint

```python
# BEFORE (lines 263-265):
# API blueprint (D2) - to be implemented
# from src.web.routes.api import api_bp
# app.register_blueprint(api_bp, url_prefix='/api')

# AFTER:
# API blueprint (D2)
from src.web.routes.api import api_bp
app.register_blueprint(api_bp, url_prefix='/api')
```

### Step 3: Create Unit Tests

**File:** `tests/unit/web/test_api_routes.py`

**Test Classes:**

1. **`TestCreateDecision`** (~15 tests)
   - `test_create_accept_decision_success` - Happy path for accept
   - `test_create_reject_decision_success` - Happy path for reject
   - `test_create_reclassify_decision_success` - Happy path for reclassify
   - `test_missing_candidate_id` - Validation error
   - `test_missing_decision` - Validation error
   - `test_invalid_decision_type` - Validation error
   - `test_accept_missing_metric_id` - Validation error
   - `test_reject_missing_category` - Validation error
   - `test_reject_invalid_category` - Validation error
   - `test_candidate_not_found` - 404 error
   - `test_candidate_already_reviewed` - 409 conflict
   - `test_invalid_json` - 400 bad request
   - `test_database_error` - 500 internal error
   - `test_next_candidate_returned` - Success includes next candidate
   - `test_last_candidate_no_next` - Success with no next candidate

2. **`TestGetCandidate`** (~5 tests - future enhancement)
   - `test_get_candidate_success`
   - `test_candidate_not_found`
   - `test_database_error`
   - `test_response_format`
   - `test_includes_decision_if_reviewed`

3. **`TestGetFilingProgress`** (~3 tests - future enhancement)
   - `test_get_progress_success`
   - `test_filing_not_found`
   - `test_database_error`

4. **`TestValidationHelpers`** (~8 tests)
   - `test_validate_accept_decision` - Requires metric_id
   - `test_validate_reject_decision` - Requires category
   - `test_validate_reclassify_decision` - Requires metric_id
   - `test_invalid_decision_type` - Error
   - `test_invalid_rejection_category` - Error
   - `test_negative_review_time` - Error
   - `test_all_optional_fields` - Accept with notes and time
   - `test_empty_request` - Multiple errors

### Step 4: Integration Test

**File:** `tests/integration/web/test_api_integration.py`

**Test Scenarios:**
1. End-to-end accept flow with database
2. End-to-end reject flow with database
3. Transaction rollback on error
4. Next candidate navigation across multiple decisions

## Validation Rules

### Request Validation

| Field | Required When | Validation |
|-------|---------------|------------|
| `candidate_id` | Always | Positive integer, must exist in database |
| `decision` | Always | Must be in DECISION_TYPES |
| `assigned_metric_id` | decision = accept/reclassify | Must exist in metrics table, status = 'active' |
| `rejection_category` | decision = reject | Must be in REJECTION_CATEGORIES |
| `rejection_reason` | Optional (reject) | String, max 500 chars |
| `reviewer_notes` | Optional | String, max 1000 chars |
| `review_time_seconds` | Optional | Positive integer |

### Business Rules

1. **Idempotency:** Reject duplicate decisions for same candidate (409 Conflict)
2. **Atomicity:** Decision insert + status update in single transaction
3. **Status transition:** `pending` → `reviewed` only (no other transitions via API)
4. **Next candidate:** Must be from same filing, status = 'pending', candidate_id > current

## Error Handling

### HTTP Status Codes

- **200 OK** - GET requests successful
- **201 Created** - Decision created successfully
- **400 Bad Request** - Validation errors, malformed JSON
- **404 Not Found** - Candidate not found
- **409 Conflict** - Candidate already has decision
- **500 Internal Server Error** - Database errors, unexpected failures

### Error Response Format

```json
{
  "status": "error",
  "message": "Human-readable error message",  // For single errors
  "errors": {                                 // For validation errors
    "field_name": "Error description"
  },
  "existing_decision_id": 123                 // For conflict errors
}
```

### Logging Strategy

- **INFO:** Successful decision creation with candidate_id and decision type
- **WARNING:** Validation failures (client errors)
- **ERROR:** Database errors, unexpected exceptions
- **DEBUG:** Request payload, next candidate lookup results

## Database Transaction Pattern

```python
try:
    # Begin implicit transaction

    # 1. Validate candidate exists and not already reviewed
    candidate = db.get_review_candidate(candidate_id)
    if not candidate:
        return jsonify({"status": "error", "message": "Candidate not found"}), 404

    existing = db.get_decision_for_candidate(candidate_id)
    if existing:
        return jsonify({
            "status": "error",
            "message": "Candidate already has a decision",
            "existing_decision_id": existing["decision_id"]
        }), 409

    # 2. Insert decision
    decision_id = db.insert_review_decision(
        candidate_id=candidate_id,
        decision=decision,
        assigned_metric_id=assigned_metric_id,
        rejection_category=rejection_category,
        rejection_reason=rejection_reason,
        reviewer_notes=reviewer_notes,
        review_time_seconds=review_time_seconds,
    )

    # 3. Update candidate status
    db.update_candidate_status(candidate_id, "reviewed")

    # Transaction commits automatically if no exceptions

    # 4. Get next candidate (outside transaction - read-only)
    next_cand = _get_next_candidate_info(db, candidate["filing_id"], candidate_id)

    return jsonify({
        "status": "success",
        "decision_id": decision_id,
        "candidate_id": candidate_id,
        "next_candidate": next_cand
    }), 201

except Exception as e:
    logger.error(f"Error creating decision: {e}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500
```

## Security Considerations

### Input Validation
- All JSON fields sanitized before database insertion
- SQL injection prevented by parameterized queries (already in db.py)
- XSS prevention: No HTML rendering of user input (JSON API only)

### Authentication (Future)
- Currently no authentication (development mode)
- Production should add:
  - Session-based auth or JWT tokens
  - CSRF protection for POST requests
  - Rate limiting on API endpoints

### Authorization (Future)
- Track `reviewer_id` when authentication added
- Audit log of who made which decisions

## Integration with Review Interface

### JavaScript Pattern (review.js)

The API will be called from `src/web/static/js/review.js`:

```javascript
async function submitDecision(decision, options = {}) {
  const payload = {
    candidate_id: currentCandidateId,
    decision: decision,
    ...options
  };

  const response = await fetch('/api/decisions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload)
  });

  const result = await response.json();

  if (result.status === 'success') {
    // Navigate to next candidate
    if (result.next_candidate) {
      window.location.href = result.next_candidate.url;
    } else {
      // All done, return to filing list
      window.location.href = '/filings';
    }
  } else {
    // Show errors
    displayErrors(result.errors || result.message);
  }
}

// Accept button
document.getElementById('accept-btn').addEventListener('click', () => {
  submitDecision('accept', {
    assigned_metric_id: currentSuggestedMetricId,
    review_time_seconds: getReviewTime()
  });
});

// Reject button
document.getElementById('reject-btn').addEventListener('click', () => {
  const category = document.getElementById('rejection-category').value;
  const reason = document.getElementById('rejection-reason').value;

  submitDecision('reject', {
    rejection_category: category,
    rejection_reason: reason,
    review_time_seconds: getReviewTime()
  });
});

// Reclassify button
document.getElementById('reclassify-btn').addEventListener('click', () => {
  const metricId = document.getElementById('reclassify-metric').value;

  submitDecision('reclassify', {
    assigned_metric_id: metricId,
    review_time_seconds: getReviewTime()
  });
});
```

## Files to Create/Modify

| File | Action | Lines | Purpose |
|------|--------|-------|---------|
| `src/web/routes/api.py` | CREATE | ~250 | API endpoints |
| `src/web/app.py` | MODIFY | +2 | Register API blueprint |
| `tests/unit/web/test_api_routes.py` | CREATE | ~500 | Unit tests |
| `tests/integration/web/test_api_integration.py` | CREATE | ~200 | Integration tests |

## Testing Strategy

### Unit Tests (Fast, No Database)
- Mock `get_db()` to return mock DatabaseAdapter
- Test all validation logic
- Test error responses
- Test response formatting
- Coverage target: 100%

### Integration Tests (Real Database)
- Use TEST_DATABASE_URL
- Create real candidates and decisions
- Verify transaction atomicity
- Test concurrent decision attempts (race conditions)
- Coverage target: All happy paths + critical error paths

### Manual Testing Checklist
- [ ] Accept decision creates record and updates status
- [ ] Reject decision with category and reason
- [ ] Reclassify decision changes metric_id
- [ ] Next candidate navigation works
- [ ] Last candidate returns null for next
- [ ] Duplicate decision returns 409
- [ ] Invalid candidate_id returns 404
- [ ] Missing required fields return 400
- [ ] Database error returns 500
- [ ] Review interface JavaScript integration works

## Implementation Timeline

**Estimated effort:** 1 day (4-6 hours coding + testing)

### Phase 1: Core Endpoint (2-3 hours)
1. Create `api.py` with `create_decision()` endpoint
2. Implement validation helper
3. Implement next candidate helper
4. Update `app.py` to register blueprint

### Phase 2: Unit Tests (1-2 hours)
1. Create test file structure
2. Write validation tests
3. Write success path tests
4. Write error path tests

### Phase 3: Integration Tests (1 hour)
1. Create integration test file
2. Write end-to-end scenarios
3. Test transaction rollback

### Phase 4: Manual Testing (30-60 minutes)
1. Start dev server
2. Test with curl/Postman
3. Verify database records
4. Test with review interface (when D4/D5 ready)

## Dependencies for Next Steps

Once D2 is complete, the following can proceed:

- **D4** (`templates/review.html`) - Can add AJAX buttons
- **D5** (`static/js/review.js`) - Can implement JavaScript to call API
- **E1** (`pattern_analyzer.py`) - Can analyze decisions from database

## Success Criteria

- [ ] All unit tests passing (>95% coverage)
- [ ] All integration tests passing
- [ ] Manual curl tests successful
- [ ] Blueprint registered in app.py
- [ ] Error responses follow documented format
- [ ] Next candidate navigation works correctly
- [ ] Atomic transactions (decision + status update)
- [ ] No SQL injection vulnerabilities
- [ ] Proper logging at all levels

## Future Enhancements (Not in Scope)

1. **Batch decisions** - Accept/reject multiple candidates at once
2. **Undo decision** - Rollback a decision and reset status to pending
3. **Edit decision** - Update an existing decision's notes or category
4. **Decision history** - Show all decisions for a candidate (if multiple reviewers)
5. **Real-time progress** - WebSocket updates for multi-user scenarios
6. **Export decisions** - Download decisions as CSV/JSON
7. **Bulk operations** - Accept all candidates matching a pattern

## References

**Codebase:**
- `src/web/app.py:71-89` - `get_db()` pattern
- `src/web/app.py:268-274` - `_wants_json_response()` helper
- `src/web/routes/review.py:285-339` - Validation helper pattern
- `src/infra/db.py:963-1069` - `insert_review_decision()` method
- `src/infra/db.py:734-767` - `update_candidate_status()` method
- `src/review/models.py:27-38` - Decision and rejection constants

**Documentation:**
- `docs/HUMAN_REVIEW_SYSTEM_PLAN.md:145-149` - Original D2 specification
- `sql/07_create_review_schema.sql` - Database schema

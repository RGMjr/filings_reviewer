# WORKER PROMPT: Task IMG-1-5 - API Routes for Image Decisions

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-1-5
TASK NAME:     Create Flask API routes for image review decisions
WORKSTREAM:    Image Review System (Phase 1)
SOURCE:        /Users/rgmarkey/.claude/plans/gentle-prancing-yao.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours
RISK LEVEL:    Low (new routes, no existing routes modified)
TASK SIZE:     M
DEPENDS ON:    IMG-1-2
UNLOCKS:       IMG-1-7
BLOCKS:        IMG-1-7, IMG-1-8
PARALLEL WITH: IMG-1-3, IMG-1-4
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create Flask API routes for AJAX-based image review decisions. These endpoints are called by JavaScript to record decisions without page reloads.

**Business Rationale**: AJAX endpoints enable fast keyboard-driven review workflow with instant feedback and auto-navigation.

**Current Behavior**: No image decision API endpoints exist.

**Desired Behavior**: Three API endpoints handle decision creation, skip, and undo operations.

## Prerequisites

- IMG-1-2 complete (database methods exist)
- Understand existing API patterns: `src/web/routes/api.py`

## Files to Create

1. **`src/web/routes/api_images.py`** - New blueprint with API routes

## Files to Modify

1. **`src/web/app.py`** - Register new blueprint (if not done in IMG-1-4)

## Files to Read (Context Only)

- `src/web/routes/api.py` - Existing API patterns (validation, responses, error handling)
- `src/infra/db.py` - Database methods (IMG-1-2)

## Implementation Requirements

### Core Functionality

1. **Blueprint Registration**
   ```python
   api_images_bp = Blueprint('api_images', __name__, url_prefix='/api')
   ```

2. **Route: `POST /api/image-decisions`**
   - Create a new image review decision
   - Request body (JSON):
     ```json
     {
       "image_candidate_id": 123,
       "decision": "relevant",        // or "not_relevant"
       "chart_type": "stacked_bar",   // required if relevant
       "rejection_reason": null,       // required if not_relevant
       "reviewer_notes": "optional",
       "review_time_seconds": 15
     }
     ```
   - Validation:
     - `image_candidate_id` required, must exist
     - `decision` required, must be "relevant" or "not_relevant"
     - `chart_type` required if decision="relevant"
     - `rejection_reason` required if decision="not_relevant"
   - Response (201 Created):
     ```json
     {
       "success": true,
       "decision_id": 456,
       "next_candidate": {
         "image_candidate_id": 124,
         "url": "/review/images/35?image_candidate_id=124"
       }
     }
     ```
   - Response if no next candidate:
     ```json
     {
       "success": true,
       "decision_id": 456,
       "next_candidate": null,
       "message": "All candidates reviewed for this filing"
     }
     ```

3. **Route: `POST /api/image-candidates/<int:image_candidate_id>/skip`**
   - Skip candidate without making a decision
   - Updates status to "skipped"
   - Response (200 OK):
     ```json
     {
       "success": true,
       "next_candidate": { ... }
     }
     ```

4. **Route: `DELETE /api/image-decisions/<int:image_decision_id>`**
   - Undo/delete a decision
   - Resets candidate status to "pending"
   - Response (200 OK):
     ```json
     {
       "success": true,
       "candidate_id": 123
     }
     ```

### Validation Error Response

All validation errors return 400 with structure:
```json
{
  "success": false,
  "error": "chart_type is required when decision is 'relevant'"
}
```

### Valid Values

**Chart Types:**
- `cohort_table`, `cohort_heatmap`, `line_chart`, `bar_chart`, `stacked_bar`, `other_chart`, `mixed`

**Rejection Reasons:**
- `decorative`, `not_a_chart`, `wrong_subject`, `duplicate`, `unreadable`, `other`

### Error Handling

- 400 for validation errors (missing fields, invalid values)
- 404 for non-existent candidate/decision IDs
- 409 for duplicate decision (candidate already has decision)
- 500 for unexpected database errors

### Logging

- Log INFO: decision created, decision deleted
- Log WARNING: validation errors
- Log ERROR: database errors

## Test Requirements

### Coverage Target: **≥ 90%** for `api_images.py`

### Test Categories (12+ tests recommended)

1. **Decision Creation Tests** (5-6 tests)
   - Creates relevant decision with chart_type
   - Creates not_relevant decision with rejection_reason
   - Returns next_candidate in response
   - Returns null next_candidate when all done
   - Validates chart_type required for relevant
   - Validates rejection_reason required for not_relevant

2. **Skip Tests** (2-3 tests)
   - Skip updates status to skipped
   - Skip returns next_candidate
   - 404 for invalid candidate_id

3. **Undo Tests** (2-3 tests)
   - Delete resets status to pending
   - 404 for invalid decision_id
   - Returns candidate_id in response

4. **Validation Tests** (2-3 tests)
   - Invalid decision value returns 400
   - Invalid chart_type returns 400
   - Missing required field returns 400

## Acceptance Criteria

- [ ] Blueprint created and registered in app.py
- [ ] `POST /api/image-decisions` creates decisions
- [ ] `POST /api/image-candidates/<id>/skip` skips candidates
- [ ] `DELETE /api/image-decisions/<id>` undoes decisions
- [ ] Validation enforces chart_type/rejection_reason requirements
- [ ] Responses include next_candidate for navigation
- [ ] Proper HTTP status codes (201, 200, 400, 404)
- [ ] JSON responses follow consistent structure
- [ ] **12+ unit tests** covering all endpoints
- [ ] **Test coverage ≥ 90%**
- [ ] All new tests pass
- [ ] All existing tests still pass

## Do NOT

- Create page routes (that's IMG-1-4)
- Create JavaScript (that's IMG-1-7)
- Modify existing API routes (`src/web/routes/api.py`)
- Add authentication (out of scope for Phase 1)

## Verification Commands

```bash
# Run tests for new API routes
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_images_routes.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_images_routes.py \
  --cov=src.web.routes.api_images --cov-report=term-missing

# Manual API test (after app running)
curl -X POST http://localhost:5000/api/image-decisions \
  -H "Content-Type: application/json" \
  -d '{"image_candidate_id": 1, "decision": "relevant", "chart_type": "bar_chart"}'
```

## Reference

- **Plan document**: `/Users/rgmarkey/.claude/plans/gentle-prancing-yao.md`
- **Existing API routes**: `src/web/routes/api.py`
- **Dependencies**: IMG-1-2 (database methods)
- **Related**: IMG-1-4 (page routes), IMG-1-7 (JavaScript consumer)

---

**Last Updated**: 2026-01-12
**Format Version**: 2.6

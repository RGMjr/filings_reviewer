# Worker Prompt: Fix 19 Failing Image Route Tests

## Task ID: REV-01
## Priority: P0 (Blocking)
## Effort: S (< 2 hours)
## Finding IDs: C-D4-001, G-D4-001, T-D4-001

---

## Problem Statement

All 19 tests in `tests/unit/web/test_api_images_routes.py` are failing with **409 CONFLICT** status codes instead of expected 201/400 responses. This is a blocking issue preventing CI from passing.

### Root Cause Analysis (from 3 models)

1. **Mock patching the wrong dependency** (GPT-4): The patch target `src.web.routes.api_images.get_db` may not match where the route actually imports from. If the route does `from src.infra.db import get_db`, the patch is a no-op.

2. **Conflict checks run before validation** (GPT-4): The route evaluates candidate state (reviewed/locked/duplicate) before validating request JSON, masking expected 400s behind 409s.

3. **Test fixtures inconsistent** (GPT-4): Mocked candidates may not include all fields the route expects (e.g., `review_status: pending`).

---

## Files to Modify

- `tests/unit/web/test_api_images_routes.py` - Fix test mocking
- `src/web/routes/api_images.py` - Potentially reorder validation vs conflict checks

---

## Acceptance Criteria

1. [ ] All 19 tests in test_api_images_routes.py pass
2. [ ] Tests that expect 400 (validation errors) receive 400, not 409
3. [ ] Tests that expect 201 (success) receive 201, not 409
4. [ ] Each test has assertion that mock_db methods were called
5. [ ] No real database is accessed during unit tests

---

## Implementation Steps

### Step 1: Diagnose the Mock Path Issue

```python
# In test file, add diagnostic:
import sys
print([k for k in sys.modules.keys() if 'db' in k])

# Check how api_images.py imports get_db:
# Option A: from src.infra.db import get_db
# Option B: from src.web.routes.api_images import get_db
```

### Step 2: Fix the Patch Target

```python
# WRONG - if route imports directly from src.infra.db:
with patch("src.web.routes.api_images.get_db", return_value=mock_db):

# CORRECT - patch where it's looked up:
with patch("src.infra.db.get_db", return_value=mock_db):
# OR if there's a module-level import in api_images.py
```

### Step 3: Add Guard Assertions

```python
def test_create_image_decision_success(client, mock_db):
    response = client.post('/api/images/decisions', ...)

    # Guard assertion - verify mock was actually used
    assert mock_db.get_image_candidate.called, "Mock DB was not used - check patch target"

    assert response.status_code == 201
```

### Step 4: Ensure Consistent Fixtures

```python
@pytest.fixture
def make_pending_candidate():
    """Factory for a pending candidate matching route contract."""
    def _make(candidate_id=1, **overrides):
        base = {
            "image_candidate_id": candidate_id,
            "review_status": "pending",
            "filing_id": 100,
            "decision": None,
            # Add all fields the route depends on
        }
        return {**base, **overrides}
    return _make
```

### Step 5: Check Route Validation Order

If tests still fail after fixing mocks, the route may need reordering:

```python
# In api_images.py - ensure validation before conflict check:
def create_image_decision():
    # 1. Validate request payload FIRST
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    errors = validate_request(data)
    if errors:
        return jsonify({"error": errors}), 400

    # 2. THEN check conflicts
    candidate = db.get_image_candidate(data["image_candidate_id"])
    if candidate["review_status"] != "pending":
        return jsonify({"error": "Already reviewed"}), 409
```

---

## Verification Commands

```bash
# Run only the failing tests
pytest tests/unit/web/test_api_images_routes.py -v

# Run with verbose output to see mock calls
pytest tests/unit/web/test_api_images_routes.py -v --capture=no

# Verify no real DB connections
pytest tests/unit/web/test_api_images_routes.py -v --tb=short 2>&1 | grep -i "connection"
```

---

## Success Metrics

- 19/19 tests passing
- Test execution time < 5 seconds (no real DB)
- CI pipeline unblocked

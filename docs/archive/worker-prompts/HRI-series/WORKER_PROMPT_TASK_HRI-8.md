# WORKER PROMPT: Task HRI-8 - Add Bulk Actions for Multi-Select Decisions

```
===============================================================================
TASK ID:       HRI-8
TASK NAME:     Add multi-select and bulk accept/reject functionality
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.4
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3 hr (backend 1 hr, frontend 1.5 hr, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (bulk operations need safety measures)
PARALLEL WITH: None (depends on HRI-6 - filtering/sorting is complete)
===============================================================================
```

## Objective

Add multi-select functionality to the review interface with bulk accept/reject actions for faster review of obvious cases. This enables reviewers to 5-10x throughput when processing batches of clear-cut candidates.

**Business Rationale**: When reviewing S-1 filings, many candidates follow clear patterns - e.g., all "user count" metrics from the same table are obviously correct, or all false-positive matches from a specific section can be rejected together. One-by-one review is unnecessarily slow for these cases.

**Current Behavior**:
- Single-candidate review only
- Each decision requires individual navigation and confirmation
- No way to batch process similar candidates

**Desired Behavior**:
- Checkbox on each candidate card in the sidebar
- "Select all visible" option in header
- Bulk accept/reject buttons appear when 1+ candidates selected
- Confirmation modal with summary before applying
- Maximum 20 candidates per bulk action (safety limit)
- Bulk actions logged in audit trail

## Prerequisites

- HRI-6 (Filtering and Sorting) - **COMPLETE** (commit 77d1c23) - Required for selecting filtered subsets
- HRI-7 (Decision History) - Not required but compatible (undo does NOT apply to bulk actions)
- Understand existing decision API in `src/web/routes/api.py:122-275`
- Understand `review_decisions` and `review_candidates` table schema

## Files to Create

1. **`tests/unit/web/test_api_bulk.py`** - Unit tests for bulk endpoint validation and edge cases
2. **`tests/integration/web/test_bulk_workflow.py`** - Integration tests for full bulk decision workflow

## Files to Modify

1. **`src/web/routes/api.py`** - Add `POST /api/bulk-decisions` endpoint
2. **`src/web/static/js/review.js`** - Add multi-select state, checkbox handlers, bulk action UI logic
3. **`src/web/templates/review.html`** - Add checkboxes to candidate list, bulk action bar, confirmation modal
4. **`src/infra/db.py`** - Add `insert_bulk_review_decisions()` method with transaction support

## Files to Read (Context Only)

- `src/web/routes/api.py:122-275` - `create_decision()` pattern for validation and response format
- `src/web/routes/api.py:417-528` - `undo_decision()` for DELETE endpoint pattern
- `src/web/static/js/review.js:260-400` - Decision submission flow and state management
- `src/web/templates/review.html:520-650` - Sidebar candidate list structure
- `src/infra/db.py:800-900` - Database transaction patterns
- `src/review/models.py` - DECISION_TYPES, REJECTION_CATEGORIES constants

## Implementation Requirements

### 1. Bulk Decision API Endpoint

**Location**: `src/web/routes/api.py`

Add new endpoint `POST /api/bulk-decisions`:

```
Request:
  POST /api/bulk-decisions
  Content-Type: application/json

  {
    "candidate_ids": [int, ...],    // Required: 1-20 candidate IDs
    "decision": "accept" | "reject", // Required: only accept/reject allowed
    "assigned_metric_id": str,       // Required for accept: metric ID
    "rejection_category": str,       // Required for reject: category
    "rejection_reason": str          // Optional for reject: reason
  }

Response (200 - Success):
  {
    "status": "success",
    "processed_count": int,
    "decision_ids": [int, ...],
    "failed_candidates": [
      {"candidate_id": int, "error": str}
    ],
    "message": "Processed N of M candidates"
  }

Response (400 - Validation Error):
  {
    "status": "error",
    "errors": {
      "candidate_ids": "Must provide 1-20 candidate IDs",
      "decision": "Bulk reclassify not allowed"
    }
  }

Response (403 - Safety Limit):
  {
    "status": "error",
    "message": "Maximum 20 candidates per bulk action"
  }
```

**Validation Requirements**:
- `candidate_ids`: Array with 1-20 integers, no duplicates
- `decision`: Only "accept" or "reject" (NOT "reclassify" - too risky for bulk)
- `assigned_metric_id`: Required if decision is "accept"
- `rejection_category`: Required if decision is "reject", must be in REJECTION_CATEGORIES
- All candidates must belong to same filing (prevent cross-filing bulk actions)
- All candidates must be in "pending" status (skip already-reviewed)

**Processing Logic**:
1. Validate request schema
2. Verify all candidates exist and are pending
3. Verify all candidates belong to same filing
4. Process each decision in a single transaction (all-or-nothing)
5. Log bulk action in `review_audit_log` with array of candidate_ids in query_params
6. Return success with list of created decision_ids

### 2. Multi-Select UI

**Location**: `src/web/templates/review.html` - Sidebar candidate list

Add to each candidate item:
- Checkbox input before candidate content
- Visual feedback when selected (highlight/border)
- Checkbox hidden for already-reviewed candidates (only pending selectable)

Add to sidebar header:
- "Select all visible" checkbox (only selects visible pending candidates)
- Selection count indicator: "N selected"
- "Clear selection" button (X icon)

**Checkbox positioning**:
```html
<li class="list-group-item candidate-item" data-candidate-id="{{ c.candidate_id }}">
  <!-- Add checkbox before existing content -->
  {% if c.review_status == 'pending' %}
    <input type="checkbox" class="form-check-input candidate-checkbox me-2"
           data-candidate-id="{{ c.candidate_id }}"
           aria-label="Select candidate {{ c.candidate_id }}">
  {% endif %}
  <!-- Existing candidate content -->
</li>
```

### 3. Bulk Action Bar

**Location**: `src/web/templates/review.html` - Fixed bar at bottom of sidebar

Show bar only when 1+ candidates selected:
- Selection count: "5 candidates selected"
- "Accept All" button (green/primary)
- "Reject All" button (red/danger)
- Bar slides up when selections made, slides down when cleared

**Layout**:
```html
<div id="bulk-action-bar" class="position-fixed bottom-0 p-3 bg-light border-top"
     style="display: none; left: 0; right: 0; z-index: 1050;">
  <div class="container-fluid">
    <div class="d-flex justify-content-between align-items-center">
      <span id="bulk-selection-count">0 candidates selected</span>
      <div>
        <button id="bulk-accept-btn" class="btn btn-success me-2">
          <i class="bi bi-check-all"></i> Accept All
        </button>
        <button id="bulk-reject-btn" class="btn btn-danger">
          <i class="bi bi-x-lg"></i> Reject All
        </button>
      </div>
    </div>
  </div>
</div>
```

### 4. Confirmation Modal

**Location**: `src/web/templates/review.html` - Modal component

Modal shows before executing bulk action:
- Summary: "You are about to [accept/reject] N candidates"
- List of affected candidates (metric name, value preview) - scrollable if many
- For accept: show which metric_id will be assigned
- For reject: show rejection category dropdown
- "Cancel" and "Confirm" buttons
- Disable confirm button while processing (show spinner)

**Modal Requirements**:
- Prevent accidental double-click (disable button on first click)
- Show progress indicator during API call
- On success: close modal, update UI, show toast notification
- On failure: show error in modal, keep modal open for retry

### 5. JavaScript Multi-Select Logic

**Location**: `src/web/static/js/review.js`

Extend state object:
```javascript
const state = {
  // ... existing state ...
  selectedCandidates: new Set(),  // Set of selected candidate_ids
  bulkMode: false                  // Whether in bulk selection mode
};
```

**Event Handlers**:
- `handleCheckboxChange(candidateId)`: Add/remove from selectedCandidates set
- `handleSelectAllVisible()`: Select all pending candidates currently visible
- `handleClearSelection()`: Clear selectedCandidates set
- `handleBulkAccept()`: Open confirmation modal for accept
- `handleBulkReject()`: Open confirmation modal with category dropdown
- `submitBulkDecision(decision, data)`: POST to /api/bulk-decisions

**UI Updates**:
- Toggle bulk action bar visibility based on selection count
- Update selection count display on each change
- Highlight selected candidate items (add CSS class)
- Update "select all" checkbox state (checked, unchecked, indeterminate)

### 6. Database Method

**Location**: `src/infra/db.py`

Add method:

```python
def insert_bulk_review_decisions(
    self,
    candidate_ids: List[int],
    decision: str,
    assigned_metric_id: Optional[str] = None,
    rejection_category: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> Tuple[List[int], List[Dict]]:
    """
    Insert multiple review decisions in a single transaction.

    All candidates must be pending. Uses a single transaction to ensure
    atomicity - either all decisions are created or none.

    Args:
        candidate_ids: List of candidate IDs to process
        decision: "accept" or "reject"
        assigned_metric_id: Metric ID for accept decisions
        rejection_category: Category for reject decisions
        rejection_reason: Optional reason for reject decisions

    Returns:
        Tuple of (decision_ids: List[int], failed: List[Dict])
        - decision_ids: IDs of successfully created decisions
        - failed: List of {"candidate_id": int, "error": str} for failures
    """
    pass
```

**Transaction Requirements**:
- Single transaction for all inserts
- Use `executemany` or batch insert for efficiency
- Update `review_candidates.review_status` for each candidate
- Rollback entire transaction on any constraint violation
- Log each failure with specific error message

### Error Handling

- **Empty selection**: Return 400 "Must select at least 1 candidate"
- **Over limit (>20)**: Return 403 "Maximum 20 candidates per bulk action"
- **Mixed filing IDs**: Return 400 "All candidates must be from same filing"
- **Already reviewed**: Skip with error in `failed_candidates`, don't fail entire batch
- **Invalid metric ID**: Return 400 with specific message
- **Database error**: Return 500, log detailed error, rollback transaction
- **Network timeout**: JavaScript should show retry option

### Performance Requirements

- Bulk API should complete in <500ms for 20 candidates
- Use database transactions (not individual inserts)
- Checkbox toggle should be instant (<50ms)
- Modal render should be instant
- Consider pagination if candidate list exceeds 50 items

## Test Requirements

### Coverage Target: **>= 90%** for bulk endpoint and related code

### Test Categories (10+ tests recommended)

1. **Bulk Accept Tests** (3 tests)
   - Bulk accept 5 pending candidates successfully
   - Verify all candidates marked as accepted with correct metric_id
   - Verify audit log entry contains all candidate_ids

2. **Bulk Reject Tests** (3 tests)
   - Bulk reject with category and reason
   - Verify rejection_category applied to all
   - Verify rejection_reason applied to all

3. **Validation Tests** (4 tests)
   - Empty candidate_ids array returns 400
   - More than 20 candidates returns 403
   - Bulk reclassify returns 400 (not allowed)
   - Mixed filing_ids returns 400

4. **Edge Case Tests** (3 tests)
   - Some candidates already reviewed (partial success)
   - Duplicate candidate_ids in request (deduplicated)
   - Invalid metric_id returns 400

### Known Edge Cases to Test

- All selected candidates already reviewed (no-op)
- Mixed reviewed/pending (skip reviewed, process pending)
- Concurrent bulk action on same candidates (race condition)
- Browser refresh during bulk operation

## Acceptance Criteria

- [ ] Checkbox appears on each pending candidate in sidebar
- [ ] "Select all visible" checkbox in sidebar header
- [ ] Selection count displays correctly as candidates are selected
- [ ] Bulk action bar appears when 1+ candidates selected
- [ ] "Accept All" button opens confirmation modal
- [ ] "Reject All" button opens confirmation modal with category dropdown
- [ ] Confirmation modal shows summary of affected candidates
- [ ] `POST /api/bulk-decisions` endpoint implemented
- [ ] Maximum 20 candidates enforced (API returns 403)
- [ ] Bulk reclassify blocked (API returns 400)
- [ ] All candidates in bulk action must be from same filing
- [ ] Successfully processed candidates update to reviewed status in UI
- [ ] Bulk actions logged in `review_audit_log` with all candidate_ids
- [ ] **10+ unit tests** covering bulk scenarios
- [ ] **Test coverage >= 90%** for new code
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] JavaScript syntax valid: `node --check src/web/static/js/review.js`

## Do NOT

- Allow bulk reclassify (too risky - requires individual metric selection)
- Allow bulk actions across multiple filings
- Allow bulk actions on already-reviewed candidates (silently skip them)
- Remove single-candidate decision flow (both should coexist)
- Store selection state server-side (use client-side state only)
- Allow undo for bulk actions (HRI-7 undo is single-decision only)
- Modify the existing `POST /api/decisions` endpoint
- Change pagination behavior (bulk actions work within current page/view)

## Verification Commands

```bash
# Run bulk API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_bulk.py -v --tb=short

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_bulk_workflow.py -v --tb=short

# Check coverage (must be >= 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_bulk.py \
  --cov=src/web/routes/api --cov-report=term-missing

# Run full web test suite to ensure no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/ tests/integration/web/ --no-cov -q

# Validate JavaScript syntax
node --check src/web/static/js/review.js

# Manual verification:
# 1. Start server: DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m flask --app src.web.app run --debug --port 5002
# 2. Navigate to a filing with 10+ pending candidates
# 3. Verify checkboxes appear on pending candidates
# 4. Select 3 candidates using checkboxes
# 5. Verify bulk action bar shows "3 candidates selected"
# 6. Click "Accept All" - verify confirmation modal
# 7. Confirm - verify all 3 marked as accepted
# 8. Verify audit_log entry (query: SELECT * FROM review_audit_log WHERE route_name LIKE '%bulk%' ORDER BY timestamp DESC LIMIT 1)
# 9. Test "Select all visible" with 10+ candidates
# 10. Try to submit more than 20 - verify 403 error
# 11. Test bulk reject with category selection
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example bulk API endpoint</summary>

```python
@api_bp.route("/bulk-decisions", methods=["POST"])
def create_bulk_decisions():
    """
    Record multiple review decisions in one request.

    Only accept and reject are allowed - reclassify requires individual review.
    Maximum 20 candidates per request.
    """
    db = get_db()

    try:
        if not request.is_json:
            return jsonify({"status": "error", "message": "Request must be JSON"}), 400

        data = request.get_json()

        # Validate request
        errors = _validate_bulk_decision_request(data)
        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        candidate_ids = list(set(data["candidate_ids"]))  # Deduplicate
        decision = data["decision"]

        # Safety limit
        if len(candidate_ids) > 20:
            return jsonify({
                "status": "error",
                "message": "Maximum 20 candidates per bulk action"
            }), 403

        # Verify all candidates are from same filing
        candidates = db.get_review_candidates_by_ids(candidate_ids)
        filing_ids = set(c["filing_id"] for c in candidates)

        if len(filing_ids) > 1:
            return jsonify({
                "status": "error",
                "message": "All candidates must be from same filing"
            }), 400

        # Process bulk decision
        decision_ids, failed = db.insert_bulk_review_decisions(
            candidate_ids=candidate_ids,
            decision=decision,
            assigned_metric_id=data.get("assigned_metric_id"),
            rejection_category=data.get("rejection_category"),
            rejection_reason=data.get("rejection_reason"),
        )

        logger.info(
            f"Bulk {decision}: processed {len(decision_ids)} of {len(candidate_ids)} candidates"
        )

        return jsonify({
            "status": "success",
            "processed_count": len(decision_ids),
            "decision_ids": decision_ids,
            "failed_candidates": failed,
            "message": f"Processed {len(decision_ids)} of {len(candidate_ids)} candidates"
        }), 200

    except Exception as e:
        logger.error(f"Error in bulk decision: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


def _validate_bulk_decision_request(data: Dict[str, Any]) -> Dict[str, str]:
    """Validate bulk decision request data."""
    errors = {}

    # Validate candidate_ids
    candidate_ids = data.get("candidate_ids")
    if not candidate_ids:
        errors["candidate_ids"] = "Required field"
    elif not isinstance(candidate_ids, list):
        errors["candidate_ids"] = "Must be an array"
    elif not all(isinstance(id, int) for id in candidate_ids):
        errors["candidate_ids"] = "All IDs must be integers"
    elif len(candidate_ids) < 1:
        errors["candidate_ids"] = "Must select at least 1 candidate"

    # Validate decision type
    decision = data.get("decision")
    if not decision:
        errors["decision"] = "Required field"
    elif decision not in ("accept", "reject"):
        errors["decision"] = "Bulk actions only support 'accept' or 'reject'"

    # Decision-specific validation
    if decision == "accept":
        if not data.get("assigned_metric_id"):
            errors["assigned_metric_id"] = "Required for bulk accept"
    elif decision == "reject":
        if not data.get("rejection_category"):
            errors["rejection_category"] = "Required for bulk reject"
        elif data["rejection_category"] not in REJECTION_CATEGORIES:
            errors["rejection_category"] = f"Must be one of: {', '.join(REJECTION_CATEGORIES)}"

    return errors
```

</details>

<details>
<summary>Expand to see example JavaScript multi-select logic</summary>

```javascript
// In src/web/static/js/review.js - extend state object
const state = {
    // ... existing state ...
    selectedCandidates: new Set(),
};

// Checkbox handler
function handleCheckboxChange(event) {
    const checkbox = event.target;
    const candidateId = parseInt(checkbox.dataset.candidateId, 10);

    if (checkbox.checked) {
        state.selectedCandidates.add(candidateId);
    } else {
        state.selectedCandidates.delete(candidateId);
    }

    updateBulkActionBar();
    updateSelectAllCheckbox();
}

// Select all visible pending candidates
function handleSelectAllVisible() {
    const selectAllCheckbox = document.getElementById('select-all-checkbox');
    const candidateCheckboxes = document.querySelectorAll('.candidate-checkbox:not(:disabled)');

    candidateCheckboxes.forEach(checkbox => {
        checkbox.checked = selectAllCheckbox.checked;
        const candidateId = parseInt(checkbox.dataset.candidateId, 10);

        if (selectAllCheckbox.checked) {
            state.selectedCandidates.add(candidateId);
        } else {
            state.selectedCandidates.delete(candidateId);
        }
    });

    updateBulkActionBar();
}

// Update bulk action bar visibility
function updateBulkActionBar() {
    const bar = document.getElementById('bulk-action-bar');
    const countSpan = document.getElementById('bulk-selection-count');
    const count = state.selectedCandidates.size;

    if (count > 0) {
        bar.style.display = 'block';
        countSpan.textContent = `${count} candidate${count > 1 ? 's' : ''} selected`;
    } else {
        bar.style.display = 'none';
    }
}

// Submit bulk decision
async function submitBulkDecision(decision, assignedMetricId = null, rejectionCategory = null, rejectionReason = null) {
    if (state.selectedCandidates.size === 0) {
        alert('No candidates selected');
        return;
    }

    if (state.selectedCandidates.size > 20) {
        alert('Maximum 20 candidates per bulk action. Please select fewer candidates.');
        return;
    }

    const payload = {
        candidate_ids: Array.from(state.selectedCandidates),
        decision: decision,
    };

    if (decision === 'accept') {
        payload.assigned_metric_id = assignedMetricId;
    } else if (decision === 'reject') {
        payload.rejection_category = rejectionCategory;
        payload.rejection_reason = rejectionReason;
    }

    try {
        const response = await fetch('/api/bulk-decisions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (data.status === 'success') {
            // Update UI for processed candidates
            data.decision_ids.forEach((_, index) => {
                const candidateId = payload.candidate_ids[index];
                updateCandidateStatus(candidateId, 'reviewed');
            });

            // Clear selection
            state.selectedCandidates.clear();
            document.querySelectorAll('.candidate-checkbox').forEach(cb => cb.checked = false);
            updateBulkActionBar();

            showToast(`${data.processed_count} candidates processed`);
        } else {
            alert(`Error: ${data.message || JSON.stringify(data.errors)}`);
        }
    } catch (error) {
        alert('Network error - please try again');
    }
}
```

</details>

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.4
- **Prerequisite task**: HRI-6 (Filtering and Sorting) - **COMPLETE**
- **Related completed tasks**:
  - HRI-1 (Fix Health Check Bug) - commit 82aa9da
  - HRI-2 (Add API Audit Logging) - commit 32291b0
  - HRI-4 (Display Confidence Scores) - commit 0417cc7
  - HRI-5 (Keyboard Shortcuts) - commit 734b52a
  - HRI-6 (Filtering and Sorting) - commit 77d1c23
- **Related pending tasks**:
  - HRI-7 (Decision History) - independent, undo does NOT apply to bulk actions
  - HRI-9 (Context Expansion) - independent

## Post-Implementation

After completing this task:

1. **Manual testing**:
   - Test checkbox selection on 3+ filings
   - Test "select all visible" with different filter combinations
   - Verify bulk accept assigns correct metric_id to all
   - Verify bulk reject applies category to all
   - Test 20-candidate limit enforcement
   - Test error handling for invalid metric IDs
   - Verify audit log entries for bulk actions

2. **Update documentation**:
   - Mark HRI-8 as complete in `docs/HUMAN_REVIEW_SYSTEM_TASKS.md`
   - Update status in `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`
   - Update progress summary tables in both documents

3. **Archive this file**:
   - Move to `docs/archive/worker-prompts/WORKER_PROMPT_TASK_HRI-8.md`

4. **Commit and push**:
   ```bash
   git add src/web/routes/api.py src/web/static/js/review.js src/web/templates/review.html
   git add src/infra/db.py
   git add tests/unit/web/test_api_bulk.py tests/integration/web/test_bulk_workflow.py
   git add docs/HUMAN_REVIEW_SYSTEM_TASKS.md docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
   git commit -m "HRI-8: Add bulk accept/reject functionality for multi-select decisions

   - Add checkboxes on pending candidates in sidebar
   - Add 'Select all visible' checkbox in sidebar header
   - Add bulk action bar with Accept All / Reject All buttons
   - Add POST /api/bulk-decisions endpoint with 20-candidate limit
   - Bulk reclassify blocked (requires individual review)
   - All candidates in bulk action must be from same filing
   - Confirmation modal with summary before processing
   - Bulk actions logged in review_audit_log with all candidate_ids
   - 10+ unit tests for bulk functionality

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"

   git push origin main
   ```

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)

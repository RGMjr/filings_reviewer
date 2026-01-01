# WORKER PROMPT: Task HRI-7 - Add Decision History Panel with Undo

```
===============================================================================
TASK ID:       HRI-7
TASK NAME:     Add sidebar panel showing recent decisions with undo capability
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.3
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2 hr (frontend 1 hr, backend 30 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-9 (Context Expansion)
===============================================================================
```

## Objective

Add a collapsible decision history panel to the review interface that shows the last 10 decisions made in the current session, with the ability to navigate to reviewed candidates and undo the most recent decision.

**Business Rationale**: Reviewers frequently need to verify or correct recent decisions. Currently, they must search through the candidate list or rely on memory. A history panel provides instant visibility into recent work and a quick path to fix mistakes.

**Current Behavior**:
- No visibility into previous decisions during a review session
- Must scroll through sidebar candidate list to find recently reviewed items
- No way to undo a decision without manually searching for the candidate
- Reviewed candidates are visually dimmed but not easily navigable

**Desired Behavior**:
- Collapsible panel showing last 10 decisions (accept/reject/reclassify)
- Click any entry to navigate directly to that candidate
- Color-coded entries: green=accept, red=reject, blue=reclassify
- "Undo" button on most recent decision only (soft-delete via API)
- History persists during session but clears on filing change

## Prerequisites

- None (standalone task)
- Read `src/web/static/js/review.js` for existing state management pattern
- Read `src/web/routes/api.py` for API endpoint patterns
- Understand `review_decisions` and `review_candidates` table relationship

## Files to Create

1. **`tests/unit/web/test_api_undo.py`** - Unit tests for undo endpoint
2. **`tests/integration/web/test_undo_workflow.py`** - Integration test for undo flow

## Files to Modify

1. **`src/web/routes/api.py`** - Add `DELETE /api/decisions/<decision_id>` undo endpoint
2. **`src/web/static/js/review.js`** - Add session history state, panel toggle, undo logic
3. **`src/web/templates/review.html`** - Add decision history panel UI
4. **`src/infra/db.py`** - Add `delete_review_decision()` and `get_decision_by_id()` methods

## Files to Read (Context Only)

- `src/web/static/js/review.js:260-340` - `submitDecision()` and `handleSubmitSuccess()` (hook for history tracking)
- `src/web/templates/review.html:520-600` - Sidebar structure (history panel goes in sidebar)
- `src/web/routes/api.py:122-275` - `create_decision()` pattern for new endpoint
- `src/infra/db.py:700-800` - Database method patterns

## Implementation Requirements

### 1. Session-Side Decision History (JavaScript)

**Location**: `src/web/static/js/review.js`

Extend the `state` object to track recent decisions:

- Add `decisionHistory: []` array to track last 10 decisions
- Each entry contains: `{ decisionId, candidateId, metricId, decision, timestamp, filingId, url }`
- On successful submission (`handleSubmitSuccess`), prepend new entry to history
- Limit history to 10 entries (shift oldest when exceeding)
- Store history in `sessionStorage` with key `decisionHistory_${filingId}`
- Clear history when `filingId` changes (detect from `data-filing-id` attribute)
- On page load, restore history from `sessionStorage` if exists

### 2. History Panel UI

**Location**: `src/web/templates/review.html` - Add in right sidebar, below candidate list

- Collapsible panel with header "Decision History" and toggle chevron
- Default state: collapsed on mobile (< 768px), expanded on desktop
- Panel shows last 10 decisions:
  - Each entry: `[badge] Metric Name (value)`
  - Badge color: `bg-success` (accept), `bg-danger` (reject), `bg-primary` (reclassify)
  - Clickable: navigates to candidate review page
  - Timestamp: "2 min ago" format (relative time)
- "Undo" button visible only on most recent entry
- Empty state: "No decisions yet this session"
- Panel remembers collapsed/expanded state in `sessionStorage`

### 3. Undo API Endpoint

**Location**: `src/web/routes/api.py`

Add new endpoint `DELETE /api/decisions/<int:decision_id>`:

```
Request:
  DELETE /api/decisions/123
  Headers: Content-Type: application/json

Response (200 - Success):
  {
    "status": "success",
    "message": "Decision reverted",
    "candidate_id": 456,
    "candidate_url": "/review/31/candidate/456"
  }

Response (404 - Not Found):
  {
    "status": "error",
    "message": "Decision not found"
  }

Response (403 - Forbidden):
  {
    "status": "error",
    "message": "Can only undo decisions from current session"
  }
```

**Undo logic**:
1. Verify decision exists (return 404 if not)
2. Optional: Verify decision was created in current session (via session_id in audit log)
3. Delete the decision record from `review_decisions`
4. Update `review_candidates` status back to `'pending'`
5. Log the undo action in `review_audit_log`
6. Return candidate URL for navigation

### 4. Database Layer

**Location**: `src/infra/db.py`

Add methods:

```python
def get_decision_by_id(self, decision_id: int) -> Optional[Dict]:
    """Get decision details by ID."""
    pass

def delete_review_decision(self, decision_id: int) -> bool:
    """
    Delete a review decision and reset candidate status.

    Performs in single transaction:
    1. Get candidate_id from decision
    2. Delete from review_decisions
    3. Update review_candidates.review_status = 'pending'

    Returns True if deleted, False if not found.
    """
    pass
```

### 5. Undo Confirmation

**Location**: JavaScript in `review.js`

- Show confirmation modal before undo: "Are you sure you want to undo this decision? The candidate will return to pending status."
- Modal has "Cancel" and "Confirm Undo" buttons
- On confirm, call `DELETE /api/decisions/{decision_id}`
- On success, remove entry from local history and refresh page or update UI

### Error Handling

- **Decision not found**: Show alert "Decision not found - it may have already been undone"
- **Session mismatch**: Show alert "Can only undo decisions from your current session"
- **Network error**: Show retry option with error message
- **Database error**: Return 500 with generic message, log detailed error

### Performance Requirements

- History panel should not add latency to page load (use sessionStorage, no API call)
- Undo API should complete in <200ms
- History updates should be instant (no server round-trip except undo)

## Test Requirements

### Coverage Target: **>= 90%** for new API endpoint and db methods

### Test Categories (8+ tests recommended)

1. **Undo API Tests** (4 tests)
   - Successful undo returns 200 and resets candidate status
   - Undo non-existent decision returns 404
   - Undo already-undone decision returns 404
   - Undo logged in audit table

2. **Database Method Tests** (2 tests)
   - `get_decision_by_id` returns correct decision
   - `delete_review_decision` deletes decision and updates candidate status

3. **Integration Tests** (2 tests)
   - Full undo workflow: create decision, undo, verify candidate is pending
   - Verify undo audit log entry created

### Known Edge Cases to Test

- Undo the only decision (candidate returns to pending correctly)
- Undo when candidate has been deleted (should fail gracefully)
- Rapid undo attempts (idempotent behavior)
- Session expiration during undo (graceful error)

## Acceptance Criteria

- [ ] Decision history panel appears in sidebar (collapsible)
- [ ] History shows last 10 decisions with color-coded badges
- [ ] Clicking history entry navigates to that candidate
- [ ] Relative timestamps display correctly ("2 min ago")
- [ ] "Undo" button visible only on most recent decision
- [ ] Confirmation modal appears before undo
- [ ] `DELETE /api/decisions/<id>` endpoint implemented
- [ ] Undo resets candidate status to 'pending'
- [ ] Undo logged in `review_audit_log`
- [ ] History persists in sessionStorage during session
- [ ] History clears when viewing different filing
- [ ] **8+ unit tests** covering undo scenarios
- [ ] **Test coverage >= 90%** for new code
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] JavaScript syntax valid: `node --check src/web/static/js/review.js`

## Do NOT

- Allow undo of decisions older than most recent (UI restriction)
- Hard delete decisions (use proper DELETE from table, let PostgreSQL handle cascades)
- Store history server-side (session-only via sessionStorage)
- Modify existing decision submission flow (only add history tracking hook)
- Change candidate list styling (history panel is separate)
- Add undo for bulk actions (out of scope, HRI-8)

## Verification Commands

```bash
# Run API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_undo.py -v --tb=short

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_undo_workflow.py -v --tb=short

# Check coverage (must be >= 90%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_undo.py tests/unit/infra/test_db_undo.py \
  --cov=src/web/routes/api --cov=src/infra/db --cov-report=term-missing

# Validate JavaScript syntax
node --check src/web/static/js/review.js

# Manual verification:
# 1. Start server: DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m flask --app src.web.app run --debug --port 5002
# 2. Navigate to a filing with candidates
# 3. Make 2-3 decisions (accept, reject, reclassify)
# 4. Verify history panel shows decisions with correct colors
# 5. Click on history entry - verify navigation works
# 6. Click "Undo" on most recent - verify confirmation modal
# 7. Confirm undo - verify candidate returns to pending status
# 8. Refresh page - verify history persists from sessionStorage
# 9. Navigate to different filing - verify history clears
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example JavaScript history tracking</summary>

```javascript
// In src/web/static/js/review.js - state object extension

const state = {
    // ... existing state ...
    decisionHistory: [],
    filingId: null
};

// History management
function initializeHistory() {
    state.filingId = parseInt(document.body.dataset.filingId, 10);
    const stored = sessionStorage.getItem(`decisionHistory_${state.filingId}`);
    if (stored) {
        state.decisionHistory = JSON.parse(stored);
    }
    renderHistoryPanel();
}

function addToHistory(decision) {
    const entry = {
        decisionId: decision.decision_id,
        candidateId: decision.candidate_id,
        decision: decision.decision,
        metricId: decision.assigned_metric_id || null,
        timestamp: Date.now(),
        url: `/review/${state.filingId}/candidate/${decision.candidate_id}`
    };

    state.decisionHistory.unshift(entry);

    // Limit to 10 entries
    if (state.decisionHistory.length > 10) {
        state.decisionHistory.pop();
    }

    // Persist to sessionStorage
    sessionStorage.setItem(
        `decisionHistory_${state.filingId}`,
        JSON.stringify(state.decisionHistory)
    );

    renderHistoryPanel();
}

function handleUndo(decisionId) {
    if (!confirm('Are you sure you want to undo this decision?')) {
        return;
    }

    fetch(`/api/decisions/${decisionId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Remove from local history
                state.decisionHistory = state.decisionHistory.filter(
                    d => d.decisionId !== decisionId
                );
                sessionStorage.setItem(
                    `decisionHistory_${state.filingId}`,
                    JSON.stringify(state.decisionHistory)
                );
                // Navigate to the candidate
                window.location.href = data.candidate_url;
            } else {
                alert(`Undo failed: ${data.message}`);
            }
        })
        .catch(error => {
            alert('Network error - please try again');
        });
}
```

</details>

<details>
<summary>Expand to see example history panel HTML</summary>

```jinja2
{# Add in sidebar, below candidate list #}
<div class="card mt-3" id="decision-history-panel">
    <div class="card-header py-2 d-flex justify-content-between align-items-center"
         style="cursor: pointer"
         data-bs-toggle="collapse"
         data-bs-target="#history-body">
        <span class="fw-semibold small">Decision History</span>
        <i class="bi bi-chevron-down" id="history-chevron"></i>
    </div>
    <div class="collapse show" id="history-body">
        <ul class="list-group list-group-flush small" id="history-list">
            {# Populated by JavaScript #}
            <li class="list-group-item text-muted fst-italic">
                No decisions yet this session
            </li>
        </ul>
    </div>
</div>
```

</details>

<details>
<summary>Expand to see example undo API endpoint</summary>

```python
@api_bp.route("/decisions/<int:decision_id>", methods=["DELETE"])
def undo_decision(decision_id: int):
    """
    Undo (delete) a review decision.

    Resets the candidate status back to 'pending'.
    Only the most recent decision should be undone (enforced client-side).
    """
    db = get_db()

    try:
        # Get decision details
        decision = db.get_decision_by_id(decision_id)
        if not decision:
            return jsonify({
                "status": "error",
                "message": "Decision not found"
            }), 404

        candidate_id = decision["candidate_id"]
        filing_id = decision["filing_id"]

        # Delete decision and reset candidate status
        success = db.delete_review_decision(decision_id)

        if not success:
            return jsonify({
                "status": "error",
                "message": "Failed to undo decision"
            }), 500

        logger.info(f"Undid decision {decision_id} for candidate {candidate_id}")

        return jsonify({
            "status": "success",
            "message": "Decision reverted",
            "candidate_id": candidate_id,
            "candidate_url": f"/review/{filing_id}/candidate/{candidate_id}"
        }), 200

    except Exception as e:
        logger.error(f"Error undoing decision {decision_id}: {e}")
        return jsonify({
            "status": "error",
            "message": "Internal server error"
        }), 500
```

</details>

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.3
- **Related completed tasks**:
  - HRI-1 (Fix Health Check Bug) - commit 82aa9da
  - HRI-2 (Add API Audit Logging) - commit 32291b0
  - HRI-4 (Display Confidence Scores) - commit 0417cc7
  - HRI-5 (Keyboard Shortcuts) - commit 734b52a
- **Related pending tasks**:
  - HRI-6 (Filtering and Sorting) - independent, can run in parallel
  - HRI-9 (Context Expansion) - can run in parallel

## Post-Implementation

After completing this task:

1. **Manual testing**:
   - Test history panel on 2+ filings
   - Verify undo works correctly
   - Test sessionStorage persistence
   - Test history clearing on filing change
   - Test mobile collapse behavior

2. **Update documentation**:
   - Mark HRI-7 as complete in `docs/HUMAN_REVIEW_SYSTEM_TASKS.md`
   - Update status in `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`

3. **Archive this file**:
   - Move to `docs/archive/worker-prompts/WORKER_PROMPT_TASK_HRI-7.md`

4. **Commit and push**:
   ```bash
   git add src/web/routes/api.py src/web/static/js/review.js src/web/templates/review.html
   git add src/infra/db.py
   git add tests/unit/web/test_api_undo.py tests/integration/web/test_undo_workflow.py
   git add docs/HUMAN_REVIEW_SYSTEM_TASKS.md docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
   git commit -m "HRI-7: Add decision history panel with undo capability

   - Add collapsible decision history panel in sidebar
   - Show last 10 decisions with color-coded badges (accept/reject/reclassify)
   - Click history entry to navigate to candidate
   - Add DELETE /api/decisions/<id> endpoint for undo
   - Undo resets candidate status to 'pending'
   - History persists in sessionStorage during session
   - Add confirmation modal before undo
   - 8+ unit tests for undo functionality

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"

   git push origin main
   ```

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)

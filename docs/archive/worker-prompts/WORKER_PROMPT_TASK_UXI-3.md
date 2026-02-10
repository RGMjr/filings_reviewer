# WORKER PROMPT: Task UXI-3 - Skip/Defer Shortcut

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-3
TASK NAME:     Add skip/defer keyboard shortcut (S key)
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2h (breakdown: JS 30 min, API 20 min, templates 20 min, testing 50 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (uses existing status system)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-1, UXI-2
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add `S` key shortcut to skip a candidate without making a decision, setting status to "skipped" and navigating to next.

**Business Rationale**: Reviewers sometimes encounter candidates they can't immediately classify (need context, unsure, want to revisit). Currently no way to defer without making a decision or manually navigating.

**Current Behavior**: No skip functionality. Reviewer must either make a decision or manually click "Next" without recording intent to revisit.

**Desired Behavior**: Pressing `S` sets candidate status to "skipped", shows brief toast confirmation, and navigates to next pending candidate. Skipped candidates visible in sidebar with distinct status badge.

## Prerequisites

- None (standalone task)

## Existing Infrastructure (Investigation 2026-01-06)

**IMPORTANT**: Skip functionality is partially implemented. This task wires up existing backend support.

| Component | Status | Details |
|-----------|--------|---------|
| `db.update_candidate_status()` | ✅ Exists | In `db.py` - Already supports `'skipped'` status |
| `db.get_review_candidate()` | ✅ Exists | In `db.py` - Returns candidate with `filing_id` |
| Filter dropdown | ✅ Exists | In `review.html` status filter - "Skipped" option present |
| Navigation helper | ✅ Exists | `_get_next_candidate_info()` in `api.py` - `'skipped'` recognized |
| Skip API endpoint | ❌ Missing | No endpoint exposes `update_candidate_status()` for skip |
| Keyboard shortcut | ❌ Missing | `review.js` has no `S` key handler |
| Sidebar badge for skipped | ❌ Missing | Only handles "reviewed" vs "Pending", no "Skipped" case |
| Header status badge | ❌ Missing | Only shows "Reviewed" vs "Pending" |
| Generic toast function | ❌ Missing | `showSuccessFlash()` expects decisionId - need generic toast |

**Key insights**:
1. "Skip" is a STATUS CHANGE, not a DECISION. Do NOT create decision records for skips. Use the existing `update_candidate_status()` method directly.
2. **Block skip for reviewed candidates** - Cannot skip a candidate that already has a decision (would lose review data).

## Files to Modify

1. **`src/web/static/js/review.js`** - Add `S` key handler, skip API call, and generic toast function
2. **`src/web/routes/api.py`** - Add skip endpoint (thin wrapper around `db.update_candidate_status()`)
3. **`src/web/templates/review.html`** - Add "Skipped" badge rendering in sidebar and header

## Files to Read (Context Only)

- `src/infra/db.py` - Search for `def update_candidate_status` and `def get_review_candidate`
- `src/web/templates/review.html` - Search for:
  - `status filter` or `Skipped` in dropdown options
  - `review_status == 'reviewed'` for header badge (add skipped case before `else`)
  - Sidebar badge section (search `Status badge` comment) - add skipped case
- `src/web/static/js/review.js` - Search for:
  - `handleKeyboardShortcut` - existing keyboard handling pattern
  - `showSuccessFlash` - toast pattern to adapt
- `src/web/routes/api.py` - Search for:
  - `def create_decision` - pattern for candidate lookup and filter extraction
  - `def _get_next_candidate_info` - navigation helper to reuse

## Implementation Requirements

### Core Functionality

1. **Keyboard Shortcut** (keyboard-only, no visible button)
   - `S` key triggers skip action
   - Ignore when focus is in text input/textarea
   - Note: No visible "Skip" button in UI - this is intentional for keyboard-focused workflow

2. **API Endpoint** (`POST /api/candidates/<id>/skip`)
   - Look up candidate using `db.get_review_candidate(candidate_id)` to get `filing_id`
   - **Block if already reviewed**: Return 400 error if `review_status == 'reviewed'`
   - Call `db.update_candidate_status(candidate_id, 'skipped')`
   - **No decision record** - skip is a status change, not a decision
   - **Extract filter params from request body** (copy pattern from `create_decision`):
     ```python
     filters = {
         "status": data.get("filter_status", "all"),
         "metric": data.get("filter_metric", "all"),
         "confidence": data.get("filter_confidence", "all"),
         "sort": data.get("filter_sort", "position"),
     }
     ```
   - Reuse `_get_next_candidate_info(db, filing_id, candidate_id, filters)` for navigation
   - Return `{ status, next_candidate: { candidate_id, url } }`
   - Handle 404 if candidate not found

3. **Navigation**
   - After successful skip, navigate to next candidate **respecting user's current filters**
   - `_get_next_candidate_info()` defaults to pending candidates when no status filter is set
   - If user has status filter (e.g., "all"), it will be respected
   - Brief toast: "Skipped - moving to next"

4. **UI Feedback**
   - Keyboard hints panel updated to show `S = Skip`
   - Add generic `showToast(message, type)` function in `review.js` for skip confirmation
     - Can reuse `showSuccessFlash` pattern but without requiring decisionId
     - Show "Skipped - moving to next" on successful skip

5. **Template Changes** (`review.html`)
   - **Sidebar badge** (search for `{# Status badge #}`): Add case for skipped status
     ```jinja
     {% elif candidate.review_status == 'skipped' %}
         <span class="badge bg-secondary" title="Skipped for later review">⏭</span>
     ```
     Insert between `{% if candidate.review_status == 'reviewed' %}` and `{% else %}` (Pending)

   - **Header status badge** (search for `current_candidate.review_status`): Add skipped case
     ```jinja
     {% elif current_candidate.review_status == 'skipped' %}
         <span class="badge bg-secondary">Skipped</span>
     ```
     Insert between "Reviewed" and "Pending" cases

   - **Keyboard shortcuts panel** (search for `Section 7: Keyboard Shortcuts Panel`): Add S key
     ```jinja
     <div class="d-flex align-items-center mb-2">
         <span class="badge bg-secondary me-2">S</span>
         <span class="small">Skip candidate</span>
     </div>
     ```
     Insert after the "Previous candidate" (P key) entry

   - **Keyboard hints footer bar** (search for `id="keyboard-hints"`): Add S key
     ```html
     <kbd class="bg-secondary text-light px-2 py-1 rounded">S</kbd> Skip
     <span class="mx-1 text-muted">|</span>
     ```
     Insert after the "Previous" entry, before "Enter"

### Error Handling

- **No next candidate**: Show "No more pending candidates" message
- **API failure**: Show error toast, stay on current candidate
- **Already skipped**: Allow re-skipping (idempotent - status update is safe)
- **Already reviewed**: Return 400 error with message "Cannot skip a reviewed candidate" - prevents losing decision data

## Test Requirements

### Coverage Target: **≥ 90%** for skip endpoint in `api.py`

### Test Categories (10+ tests)

1. **Keyboard Handling** (2 tests - Playwright E2E)
   - `S` key triggers skip when not in input
   - `S` key types "s" when in textarea (no skip triggered)

2. **API Behavior** (6 tests)
   - Skip sets status to "skipped" and returns success
   - Skip returns next candidate URL with filters preserved
   - Skip with no next candidate returns `next_candidate: null`
   - Skip with invalid candidate_id returns 404
   - **Skip already-reviewed candidate returns 400** (edge case: protect decision data)
   - **Re-skip already-skipped candidate succeeds** (idempotency test)

3. **Navigation** (1 test)
   - After skip, navigates to next with filters preserved in URL

4. **Template Rendering** (1 test - integration)
   - Skipped candidate displays correct badge in sidebar

## Acceptance Criteria

- [ ] `S` key triggers skip action
- [ ] Skip sets candidate status to "skipped"
- [ ] Navigation to next candidate after skip (respects current filters)
- [ ] Toast confirmation shown ("Skipped - moving to next")
- [ ] Sidebar shows "Skipped" badge (⏭) for skipped candidates
- [ ] Header shows "Skipped" badge for current skipped candidate
- [ ] Keyboard hints updated with `S = Skip` (both panel and footer bar)
- [ ] `S` does NOT trigger when typing in text fields
- [ ] Filter state preserved during navigation
- [ ] Skip blocked for reviewed candidates (returns 400)
- [ ] Re-skip of already-skipped candidate succeeds (idempotent)
- [ ] API endpoint tests pass with ≥ 90% coverage

## Do NOT

- Create new status values (use existing "skipped")
- Modify decision creation logic
- Add skip to bulk actions (separate task if needed)
- Add complex styling changes beyond badge additions

## Verification Commands

```bash
# Run API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_routes.py -v -k skip

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_review_workflow.py -v -k skip

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api_routes.py \
  --cov=src.web.routes.api --cov-report=term-missing -k skip

# Start dev server for E2E testing
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug &
```

### Playwright E2E Tests (via MCP)

Use the Playwright MCP server for browser automation testing:

```
# Test 1: Skip keyboard shortcut works
1. browser_navigate to /review/filings/<filing_id>/candidates/<candidate_id>
2. browser_snapshot to verify candidate is displayed
3. browser_press_key 'S'
4. browser_wait_for toast notification
5. browser_snapshot to verify navigation to next candidate

# Test 2: S key types in textarea (not shortcut)
1. browser_navigate to a candidate page
2. browser_click on rejection reason textarea
3. browser_type 's'
4. browser_snapshot to verify 's' was typed (no skip occurred)

# Test 3: Skip all candidates shows completion message
1. browser_navigate to last pending candidate
2. browser_press_key 'S'
3. browser_wait_for "No more pending candidates" message
4. browser_snapshot to verify message displayed
```

## Critical Evaluation Phase

**Required for all tasks. Depth: Standard (S task)**

After verification passes but BEFORE committing:
1. Code Quality Review - Check for linting issues
2. Test Coverage Assessment - Verify 90%+ on skip logic
3. Architecture Alignment - Ensure matches existing API patterns
4. Identify Improvements - Note edge cases
5. **User Approval (REQUIRED)** - STOP and ask before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for deferred improvements
8. Commit and Push

## Reference

- **Issue source**: UI/UX Review (2026-01-06)
- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`
- **Related**: HRI-5 (Original keyboard shortcuts)

---

**Last Updated**: 2026-01-07 (revised after second critical evaluation)
**Format Version**: 2.6
**Revision History**:
- 2026-01-07 (v3): Critical evaluation updates:
  - Added filter extraction pattern with code example
  - Added "block skip for reviewed candidates" requirement (400 error)
  - Clarified navigation respects user's filter settings
  - Added 2 edge case tests (skip reviewed, re-skip idempotency)
  - Removed fragile line numbers, using semantic search instructions
  - Clarified keyboard-only (no button) is intentional
  - Updated test count from 8+ to 10+
- 2026-01-07 (v2): Added missing template requirements (sidebar/header badges), generic toast function, 404 handling, updated time estimate to 1.5h
- 2026-01-06 (v1): Initial version - clarified scope after investigation confirmed `db.update_candidate_status()` already exists

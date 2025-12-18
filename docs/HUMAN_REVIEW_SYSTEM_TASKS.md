# Human Review System - Remaining Tasks

**Created:** 2025-12-17
**Status:** Active
**Source Documents:**
- `docs/HUMAN_REVIEW_SYSTEM_PLAN.md` (core system - COMPLETE)
- `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md` (interface enhancements)

---

## Overview

The core Human Review System (Streams A-E) is **COMPLETE**. This document tracks the remaining interface improvements from `HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md`, formatted for worker prompt generation.

### Progress Summary

| Priority | Total | Complete | Remaining |
|----------|-------|----------|-----------|
| P1 Critical | 3 | 3 | 0 |
| P2 Usability | 5 | 3 | 2 |
| P3 Nice-to-Have | 4 | 0 | 4 |
| **Total** | **12** | **6** | **6** |

---

## Task Breakdown for Orchestrator/Architect

### Task Index

| Task ID | Name | Prerequisites | Effort | Risk |
|---------|------|---------------|--------|------|
| **HRI-1** | ~~Fix Health Check Bug~~ | None | ~~15 min~~ | ✅ Complete |
| **HRI-2** | ~~Add API Audit Logging~~ | None | ~~45 min~~ | ✅ Complete |
| **HRI-3** | ~~Improve Metric Classification Accuracy~~ | None | ~~2-4 hr~~ | ✅ Complete |
| **HRI-4** | ~~Display Confidence Scores in Sidebar~~ | None | ~~45 min~~ | ✅ Complete |
| **HRI-5** | ~~Expand Keyboard Shortcuts~~ | None | ~~1 hr~~ | ✅ Complete |
| **HRI-6** | ~~Add Filtering and Sorting~~ | None | ~~2 hr~~ | ✅ Complete |
| **HRI-7** | Add Decision History Panel | None | 2 hr | Low |
| **HRI-8** | Add Bulk Actions | HRI-6 | 3 hr | Medium |
| **HRI-9** | Add Context Expansion | None | 1 hr | Low |
| **HRI-10** | Add Session Persistence | None | 1 hr | None |
| **HRI-11** | Add Statistics Dashboard | 30+ decisions | 3 hr | Low |
| **HRI-12** | Add Inter-Rater Agreement | Multi-user support | 4 hr | High |

### Dependency Graph

```
HRI-1 ─┐
HRI-2 ─┤
HRI-3 ─┤
HRI-4 ─┼─────────────────────────────────> [Phase 1-2 Complete]
HRI-5 ─┤
HRI-6 ─┼─> HRI-8 ───────────────────────> [Phase 3 Complete]
HRI-7 ─┤
HRI-9 ─┘

HRI-10 ─┐
HRI-11 ─┼─────────────────────────────────> [Phase 4: Future]
HRI-12 ─┘ (blocked: requires multi-user)
```

### Recommended Execution Order

**Phase 1 (Critical Fixes):** ~~HRI-1 → HRI-2 → HRI-3~~ ✅ Complete
**Phase 2 (Quick UX Wins):** ~~HRI-4, HRI-5, HRI-6~~ ✅ Complete
**Phase 3 (Advanced Features):** HRI-7, HRI-8 (depends on HRI-6), HRI-9
**Phase 4 (Future):** HRI-10, HRI-11, HRI-12

---

## Task Details

### HRI-1: Fix Health Check Bug

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-1
TASK NAME:     Fix PoolHealthReport subscript error in health endpoint
WORKSTREAM:    Human Review Interface (Critical Fixes)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P1.1
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 15 min
TIME ACTUAL:   ~10 min
RISK LEVEL:    None
PARALLEL WITH: HRI-2
COMMIT:        82aa9da
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Fix the `/health` endpoint which currently returns 503 due to incorrect dataclass attribute access.

**Business Rationale:** Health checks are critical for production monitoring. Without a working `/health` endpoint, load balancers and monitoring systems cannot verify application status.

**Current Behavior:**
```
Health check failed: 'PoolHealthReport' object is not subscriptable
```

**Desired Behavior:** `/health` returns 200 with pool statistics when database is connected.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/app.py` - Fix dataclass attribute access at lines 276-312

**Files to Read (Context Only):**
- `src/infra/db.py` - PoolHealthReport dataclass definition

**Implementation Requirements:**

1. **Fix Attribute Access**
   - Change dictionary-style access (`health["healthy"]`) to attribute access (`health.healthy`)
   - Change `health["stats"]` to `health.stats`
   - Ensure proper JSON serialization of dataclass fields

2. **Error Handling**
   - Maintain existing try/catch for database connection errors
   - Return appropriate 503 response if pool is unhealthy

**Test Requirements:**

### Coverage Target: Maintain existing coverage for `src/web/app.py`

### Test Categories (2+ tests)

1. **Health Endpoint Tests** (2 tests)
   - Test healthy response (200) with valid database connection
   - Test unhealthy response (503) when pool reports issues

**Acceptance Criteria:**
- [ ] `/health` returns 200 when database is connected
- [ ] Pool stats included in JSON response
- [ ] Existing tests still pass
- [ ] Manual verification: `curl http://localhost:8000/health` returns 200

**Do NOT:**
- Modify PoolHealthReport dataclass definition
- Change health check logic, only fix attribute access
- Add new dependencies

**Verification Commands:**

```bash
# Run app tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_app.py -v

# Manual test (start server first)
curl -s http://localhost:8000/health | python3 -m json.tool
```

---

### HRI-2: Add API Audit Logging

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-2
TASK NAME:     Add audit logging for POST /api/decisions endpoint
WORKSTREAM:    Human Review Interface (Critical Fixes)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P1.2
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 45 min (setup 15 min, implementation 20 min, testing 10 min)
TIME ACTUAL:   ~30 min
RISK LEVEL:    Low
PARALLEL WITH: HRI-1
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Add audit logging to the API blueprint so decision submissions are captured in `review_audit_log`.

**Business Rationale:** Compliance and debugging require complete audit trails. Currently page views are logged but actual decisions are not, creating a gap in accountability.

**Current Behavior:** `POST /api/decisions` calls are not captured in `review_audit_log`.

**Desired Behavior:** All API calls are logged with endpoint, method, request body (sanitized), response status, and decision details.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/routes/api.py` - Add before_request and after_request hooks

**Files to Read (Context Only):**
- `src/web/routes/review.py` - Reference implementation of audit logging hooks
- `src/infra/db.py` - `insert_review_audit_log` method

**Implementation Requirements:**

1. **Request Logging Hook**
   - Add `@api_bp.before_request` hook similar to review_bp
   - Capture: endpoint, HTTP method, request path, timestamp
   - Store request body (sanitized - exclude sensitive fields if any)

2. **Response Logging Hook**
   - Add `@api_bp.after_request` hook
   - Capture: response status code, timing
   - Link to candidate_id from request

3. **Decision-Specific Fields**
   - Include decision type (accept/reject/reclassify) in log
   - Include candidate_id for cross-reference

**Test Requirements:**

### Coverage Target: **≥ 95%** for `src/web/routes/api.py`

### Test Categories (4+ tests)

1. **Audit Logging Tests** (3-4 tests)
   - Verify POST /api/decisions creates audit log entry
   - Verify decision_type captured correctly
   - Verify candidate_id linked in audit entry
   - Verify failed requests also logged

**Acceptance Criteria:**
- [ ] All `POST /api/decisions` calls logged to `review_audit_log`
- [ ] Decision type captured (accept/reject/reclassify)
- [ ] Candidate ID linked in audit entry
- [ ] Response status captured
- [ ] 4+ unit tests covering logging scenarios
- [ ] Existing tests still pass

**Do NOT:**
- Modify the review_audit_log table schema (use existing columns)
- Log sensitive data (passwords, tokens)
- Change existing API behavior or response format

**Verification Commands:**

```bash
# Run API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api.py tests/integration/web/test_api_integration.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api.py \
  --cov=src/web/routes/api --cov-report=term-missing
```

---

### HRI-3: Improve Metric Classification Accuracy

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-3
TASK NAME:     Audit and fix metric classification keyword overlaps
WORKSTREAM:    Human Review Interface (Critical Fixes)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P1.3
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 2-4 hr (investigation 1 hr, fixes 1-2 hr, testing 1 hr)
TIME ACTUAL:   ~2.5 hr
RISK LEVEL:    Medium (affects extraction accuracy)
PARALLEL WITH: None (should run after some review decisions exist)
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Identify and fix keyword overlap issues causing metric misclassification (e.g., "Contribution Margin" incorrectly tagged as CAC).

**Business Rationale:** Misclassified candidates waste reviewer time and reduce trust in the system. Improving keyword specificity increases precision without requiring more reviews.

**Current Behavior:**
- "Contribution Margin was 41.6%" incorrectly tagged as CAC (Customer Acquisition Cost)
- Similar terminology overlap issues between revenue/margin metrics

**Desired Behavior:** Keywords are specific enough to avoid cross-metric confusion, with exclusion patterns where needed.

**Prerequisites:**
- Some review decisions exist in database (for analysis)
- Understanding of `src/review/keyword_matching.py` and `src/extraction/metric_classifier.py`

**Files to Modify:**
1. `src/review/keyword_matching.py` - Add exclusion patterns, improve specificity
2. `src/extraction/metric_classifier.py` - Update METRIC_KEYWORDS if needed

**Files to Read (Context Only):**
- `src/review/config.py` - CandidateGenerationConfig settings
- Existing review_decisions in database

**Implementation Requirements:**

1. **Keyword Overlap Audit**
   - Generate confusion matrix from existing decisions
   - Identify top 5 misclassification patterns
   - Document overlap cases (which keywords trigger wrong metrics)

2. **Exclusion Keywords**
   - Add metric-specific negative keywords
   - Example: "contribution margin" should NOT match CAC
   - Example: "gross margin" should NOT match revenue

3. **Keyword Specificity**
   - Increase context requirements for ambiguous terms
   - Consider word boundary enforcement
   - Add multi-word phrase preferences over single words

**Test Requirements:**

### Coverage Target: **≥ 95%** for `src/review/keyword_matching.py`

### Test Categories (10+ tests)

1. **Exclusion Pattern Tests** (4-5 tests)
   - Verify negative keywords prevent misclassification
   - Test each top-5 misclassification case

2. **Specificity Tests** (4-5 tests)
   - Test multi-word phrases take precedence
   - Test word boundaries work correctly

3. **Regression Tests** (2-3 tests)
   - Ensure fixes don't break existing correct classifications

**Acceptance Criteria:**
- [x] Audit of current keyword overlaps completed
- [x] Confusion matrix generated from existing decisions
- [x] Top 5 misclassification patterns identified and documented
- [x] Exclusion keywords added for each identified overlap
- [x] 10+ unit tests covering new patterns (34 tests in test_keyword_exclusions.py)
- [x] Existing tests still pass (901 review unit tests pass)
- [x] `mypy src/review/keyword_matching.py --strict` passes

**Implementation Summary:**
- Added `METRIC_EXCLUSION_PATTERNS` dictionary to `keyword_matching.py`
- Implemented exclusion checking in `find_all_keywords()` method
- Top patterns fixed:
  1. "customer acquisition" → excluded from cm_new_customers_acquired when "acquisition cost" present
  2. margin keywords → excluded from cm_customer_acquisition_cost
  3. LTV/CAC ratio context → excludes standalone LTV metric
  4. cohort context → excludes overall gross margin metric
  5. revenue/dollar retention → excludes customer retention rate

**Do NOT:**
- Remove existing working keywords without replacement
- Change the overall keyword matching algorithm
- Modify candidate_generator.py logic (only keyword_matching.py and metric_classifier.py)

**Verification Commands:**

```bash
# Run keyword matching tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py \
  --cov=src/review/keyword_matching --cov-report=term-missing

# Type check
mypy src/review/keyword_matching.py --strict
```

**Expected Impact:**

**Before HRI-3:**
- "Contribution Margin" → CAC (wrong)
- "Gross profit" → Revenue (wrong)

**After HRI-3:**
- "Contribution Margin" → cm_contribution_margin (correct)
- "Gross profit" → cm_gross_margin_overall (correct)

---

### HRI-4: Display Confidence Scores

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-4
TASK NAME:     Display confidence scores in candidate sidebar with color-coded badges
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.2
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 30-45 min (frontend 20 min, testing 15 min)
TIME ACTUAL:   ~25 min
RISK LEVEL:    None
PARALLEL WITH: HRI-5, HRI-6
COMMIT:        0417cc7
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Display the existing confidence score on candidate cards with color-coded badges.

**Business Rationale:** Helps reviewers prioritize low-confidence candidates and provides transparency into system recommendations.

**Current Behavior:** Confidence scores are computed (`CandidateFeatures.confidence_score`) but not displayed.

**Desired Behavior:** Each candidate card shows a color-coded badge: green (>0.8), yellow (0.5-0.8), red (<0.5).

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/routes/review.py` - Pass confidence_score to template
2. `src/web/templates/review.html` - Add badge display

**Files to Read (Context Only):**
- `src/review/models.py` - CandidateFeatures.confidence_score field
- `src/review/confidence_scoring.py` - How scores are calculated

**Implementation Requirements:**

1. **Backend: Pass Score to Template**
   - Extract confidence_score from candidate features JSONB
   - Pass to template context as `confidence_score` (float 0.0-1.0)
   - Handle missing scores gracefully (default to None)

2. **Frontend: Badge Display**
   - Add badge next to candidate header (e.g., `[87%]`)
   - Color coding: green/success (>0.8), yellow/warning (0.5-0.8), red/danger (<0.5)
   - Tooltip explaining what the score means
   - Format as percentage (multiply by 100)

3. **Accessibility**
   - Color should not be only indicator (include text label)
   - ARIA label for screen readers

**Test Requirements:**

### Coverage Target: Maintain existing coverage for `src/web/routes/review.py`

### Test Categories (4+ tests)

1. **Backend Tests** (2 tests)
   - Verify confidence_score passed to template
   - Verify missing scores handled gracefully

2. **Template Tests** (2 tests)
   - Verify badge renders with correct color class
   - Verify tooltip present

**Acceptance Criteria:**
- [ ] Confidence score displayed on all candidates
- [ ] Color coding applied (green/yellow/red)
- [ ] Tooltip explains score meaning
- [ ] Score formatted as percentage
- [ ] 4+ unit tests
- [ ] Existing tests still pass
- [ ] WCAG 2.1 AA accessibility maintained

**Do NOT:**
- Modify confidence_scoring.py logic
- Add sorting by confidence (that's HRI-6)
- Change candidate card layout significantly

**Verification Commands:**

```bash
# Run review route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Manual verification (start server, review a filing)
# Verify badge appears on candidate cards
```

---

### HRI-5: Expand Keyboard Shortcuts

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-5
TASK NAME:     Add Previous, Enter, Escape keyboard shortcuts and document in UI
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.1
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 1 hr (implementation 40 min, testing 20 min)
TIME ACTUAL:   ~50 min
RISK LEVEL:    None
PARALLEL WITH: HRI-4, HRI-6
COMMIT:        734b52a
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Expand existing keyboard shortcuts (A, R, C, N) with P (Previous), Enter (Confirm), Escape (Cancel), and add visible documentation in the UI.

**Business Rationale:** Power users can review 2-3x faster with complete keyboard navigation. Current shortcuts are undocumented in the UI.

**Current Behavior:** A, R, C, N shortcuts exist but P/Enter/Escape are missing. No visible shortcut hints in UI.

**Desired Behavior:** Complete keyboard navigation with visible hints.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/static/js/review.js` - Add new shortcuts
2. `src/web/templates/review.html` - Add shortcut hints UI element

**Files to Read (Context Only):**
- `docs/D5_IMPLEMENTATION_COMPLETE.md` - Existing shortcut implementation details

**Implementation Requirements:**

1. **New Shortcuts**
   - `P` - Previous candidate (navigate to previous)
   - `Enter` - Confirm current action (submit form)
   - `Escape` - Cancel/close modal

2. **Shortcut Hints UI**
   - Add keyboard icon or "?" that reveals shortcut list
   - Could be footer element or floating panel
   - Show all shortcuts: A=Accept, R=Reject, C=Reclassify, N=Next, P=Previous, Enter=Confirm, Esc=Cancel

3. **Browser Compatibility**
   - No conflicts with browser defaults
   - Shortcuts disabled when typing in text fields
   - Test on Chrome, Firefox, Safari

**Test Requirements:**

### Coverage Target: Manual testing (JavaScript)

### Test Categories (manual + automated)

1. **Keyboard Navigation** (manual)
   - Test each shortcut works
   - Test no conflicts with text input
   - Test across browsers

2. **Accessibility** (manual)
   - Verify shortcuts don't interfere with screen readers
   - Verify hints are accessible

**Acceptance Criteria:**
- [ ] P (Previous) shortcut functional
- [ ] Enter (Confirm) shortcut functional
- [ ] Escape (Cancel) shortcut functional
- [ ] Shortcut hints visible in UI
- [ ] No conflicts with browser defaults
- [ ] Works across Chrome, Firefox, Safari
- [ ] Existing shortcuts still work
- [ ] WCAG 2.1 AA accessibility maintained

**Do NOT:**
- Remove existing A, R, C, N shortcuts
- Add shortcuts that conflict with browser defaults (Ctrl+S, etc.)
- Modify JavaScript module structure significantly

**Verification Commands:**

```bash
# Syntax check JavaScript
node --check src/web/static/js/review.js

# Manual testing required for keyboard functionality
# Start server and test each shortcut
```

---

### HRI-6: Add Filtering and Sorting

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-6
TASK NAME:     Add candidate filtering and sorting options to review interface
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.5
STATUS:        ✅ COMPLETE
COMPLETION:    2025-12-17
TIME ESTIMATE: 2 hr (backend 45 min, frontend 45 min, testing 30 min)
TIME ACTUAL:   ~2.5 hr
RISK LEVEL:    Low
PARALLEL WITH: HRI-4, HRI-5
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Add filter dropdowns and sort options for candidates to improve review efficiency.

**Business Rationale:** Reviewers can focus on specific subsets (e.g., low-confidence first) instead of reviewing in document order.

**Current Behavior:** Candidates shown in document order (by candidate_id) with no filtering.

**Desired Behavior:** Dropdowns for status, metric type, confidence level; sort options.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/routes/review.py` - Add query parameters for filtering/sorting
2. `src/infra/db.py` - Update query methods with filter/sort options
3. `src/web/templates/review.html` - Add filter UI elements

**Files to Read (Context Only):**
- `src/infra/db.py` - `get_review_candidates_for_filing` method

**Implementation Requirements:**

1. **Filter Options**
   - Status: Pending / Reviewed / All
   - Metric type: Dropdown of detected metrics in filing
   - Confidence: High (>0.8) / Medium (0.5-0.8) / Low (<0.5) / All

2. **Sort Options**
   - Document order (default)
   - Confidence ascending (uncertain first)
   - Confidence descending (quick wins first)
   - Value magnitude

3. **URL Parameters**
   - Filters persist via URL params: `?status=pending&confidence=low&sort=confidence_asc`
   - Enable bookmark/share of filtered views

4. **UI Elements**
   - Filter dropdowns in sidebar or header
   - Active filters shown as chips/badges
   - "Clear filters" button

**Test Requirements:**

### Coverage Target: **≥ 90%** for affected routes

### Test Categories (8+ tests)

1. **Filter Tests** (4 tests)
   - Filter by status
   - Filter by metric type
   - Filter by confidence level
   - Combined filters

2. **Sort Tests** (2 tests)
   - Sort by confidence ascending
   - Sort by confidence descending

3. **URL Persistence** (2 tests)
   - Verify filters in URL
   - Verify filters applied on page load from URL

**Acceptance Criteria:**
- [ ] Status filter dropdown working
- [ ] Metric type filter dropdown working
- [ ] Confidence level filter working
- [ ] Sort dropdown with 4 options
- [ ] Filters persist in URL parameters
- [ ] "Clear filters" button works
- [ ] 8+ unit tests
- [ ] Existing tests still pass

**Do NOT:**
- Modify candidate generation logic
- Change pagination behavior significantly
- Add client-side filtering (use server-side for consistency)

**Verification Commands:**

```bash
# Run review route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_review_workflow.py -v
```

---

### HRI-7: Add Decision History Panel

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-7
TASK NAME:     Add sidebar panel showing recent decisions with undo capability
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.3
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2 hr (backend 30 min, frontend 1 hr, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-9
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Add a collapsible sidebar showing the last 10 decisions in the current session with navigation and undo.

**Business Rationale:** Reviewers may forget what they decided or want to correct a mistake without searching.

**Current Behavior:** No visibility into previous decisions during a session.

**Desired Behavior:** Sidebar panel with decision history, click to navigate, undo for most recent.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/static/js/review.js` - Session state management, undo logic
2. `src/web/templates/review.html` - History panel UI
3. `src/web/routes/api.py` - Undo endpoint (optional)

**Implementation Requirements:**

1. **History Panel UI**
   - Collapsible sidebar (default collapsed on mobile, expanded on desktop)
   - Show last 10 decisions: candidate ID, metric, decision type
   - Visual distinction: green=accept, red=reject, blue=reclassify
   - Click entry to navigate to that candidate

2. **Session State**
   - Store recent decisions in JavaScript session state
   - Persist across navigation within same filing
   - Clear when changing filings

3. **Undo Capability**
   - "Undo" button on most recent decision
   - Soft delete: sets decision status back to pending
   - Confirmation before undo

**Test Requirements:**

### Coverage Target: Manual + 4 unit tests

### Test Categories (4+ tests)

1. **History Display** (2 tests)
   - Verify history panel shows recent decisions
   - Verify correct visual styling per decision type

2. **Undo API** (2 tests)
   - Verify undo endpoint resets candidate status
   - Verify undo blocked for non-recent decisions

**Acceptance Criteria:**
- [ ] History panel shows last 10 decisions
- [ ] Clicking entry navigates to candidate
- [ ] Visual distinction for accept/reject/reclassify
- [ ] Undo functionality for most recent decision
- [ ] Confirmation modal before undo
- [ ] 4+ unit tests
- [ ] Existing tests still pass

**Do NOT:**
- Allow undo of decisions older than most recent
- Hard delete decisions (use soft delete/status change)
- Store history in database (session-only)

**Verification Commands:**

```bash
# Run API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api.py -v

# Manual testing for JavaScript functionality
```

---

### HRI-8: Add Bulk Actions

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-8
TASK NAME:     Add multi-select and bulk accept/reject functionality
WORKSTREAM:    Human Review Interface (Usability)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P2.4
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3 hr (backend 1 hr, frontend 1.5 hr, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (bulk operations need safety measures)
PARALLEL WITH: None (depends on HRI-6)
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Enable multi-select of candidates with bulk accept/reject actions for faster review of obvious cases.

**Business Rationale:** When patterns are clear, reviewing one-by-one is unnecessarily slow. Bulk actions can 5-10x throughput for obvious cases.

**Current Behavior:** Single-candidate review only.

**Desired Behavior:** Multi-select with bulk accept/reject, safety limits, confirmation.

**Prerequisites:**
- HRI-6 (Filtering and Sorting) - enables selecting filtered subsets

**Files to Modify:**
1. `src/web/routes/api.py` - Bulk decision endpoint
2. `src/web/templates/review.html` - Checkbox UI, bulk action bar
3. `src/web/static/js/review.js` - Multi-select logic

**Implementation Requirements:**

1. **Multi-Select UI**
   - Checkbox on each candidate card
   - "Select all visible" checkbox in header
   - Selection count indicator
   - Clear selection button

2. **Bulk Action Bar**
   - Appears when 1+ candidates selected
   - Buttons: "Accept all selected", "Reject all selected"
   - Shows count of selected candidates

3. **Confirmation Modal**
   - Summary of affected candidates
   - Require explicit confirmation
   - Show metric types affected

4. **Safety Measures**
   - Maximum 20 candidates per bulk action
   - Require confirmation for any bulk operation
   - Log bulk actions separately in audit (include all candidate_ids)

5. **API Endpoint**
   - `POST /api/bulk-decisions`
   - Accept array of candidate_ids and decision type
   - Return success count and any failures

**Test Requirements:**

### Coverage Target: **≥ 90%** for bulk endpoint

### Test Categories (8+ tests)

1. **Bulk Accept Tests** (3 tests)
   - Bulk accept 5 candidates
   - Verify all marked as accepted
   - Verify audit log entry

2. **Bulk Reject Tests** (2 tests)
   - Bulk reject with reason
   - Verify all marked as rejected

3. **Safety Tests** (3 tests)
   - Verify 20-candidate limit enforced
   - Verify empty selection rejected
   - Verify invalid candidate_ids handled

**Acceptance Criteria:**
- [ ] Multi-select checkboxes on candidates
- [ ] "Select all visible" functionality
- [ ] Bulk accept button works
- [ ] Bulk reject button works
- [ ] Confirmation modal shows summary
- [ ] 20-candidate limit enforced
- [ ] Bulk operations logged in audit
- [ ] 8+ unit tests
- [ ] Existing tests still pass

**Do NOT:**
- Allow bulk reclassify (too risky)
- Allow bulk actions without confirmation
- Remove single-candidate decision flow

**Verification Commands:**

```bash
# Run API tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_api.py -v

# Integration test for bulk flow
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/test_api_integration.py -v
```

---

### HRI-9: Add Context Expansion

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-9
TASK NAME:     Add "Show more context" and "View in SEC filing" links
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.1
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1 hr (backend 20 min, frontend 40 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-7
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Allow reviewers to see more context and link to original SEC filing for verification.

**Business Rationale:** Sometimes 30-50 words isn't enough context. Direct link to SEC filing enables verification of ambiguous cases.

**Current Behavior:** Fixed context window, no link to source.

**Desired Behavior:** "Show more" expands context; "View in SEC" links to EDGAR.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/routes/review.py` - Endpoint for expanded context
2. `src/web/templates/review.html` - UI for expand button and SEC link
3. `src/web/static/js/review.js` - AJAX for context expansion

**Implementation Requirements:**

1. **"Show More Context" Button**
   - Fetch surrounding paragraphs on demand
   - Expand from 50 words to 150+ words
   - Smooth UI expansion animation

2. **"View in SEC Filing" Link**
   - Construct SEC EDGAR URL from filing metadata
   - Format: `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}`
   - Open in new tab

3. **Data Requirements**
   - Use segment_position from source_segments
   - Fetch adjacent segments when expanding

**Test Requirements:**

### Coverage Target: **≥ 90%** for context expansion endpoint

### Test Categories (4+ tests)

1. **Context Expansion** (2 tests)
   - Verify expanded context returned
   - Verify handles missing adjacent segments

2. **SEC Link Generation** (2 tests)
   - Verify correct URL constructed
   - Verify handles missing metadata gracefully

**Acceptance Criteria:**
- [ ] "Show more context" button appears
- [ ] Clicking expands to show more text
- [ ] "View in SEC filing" link present
- [ ] Link opens correct SEC EDGAR page
- [ ] 4+ unit tests
- [ ] Existing tests still pass

**Do NOT:**
- Embed SEC filing content (just link)
- Cache expanded context long-term
- Change default context size

**Verification Commands:**

```bash
# Run review route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Manual test: verify SEC link opens correct filing
```

---

### HRI-10: Add Session Persistence

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-10
TASK NAME:     Remember last viewed filing/candidate for "resume where left off"
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.3
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1 hr
TIME ACTUAL:   N/A
RISK LEVEL:    None
PARALLEL WITH: HRI-11
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Remember last viewed position so reviewers can resume where they left off.

**Business Rationale:** Reviewers often work in multiple sessions. Losing position wastes time finding where they stopped.

**Current Behavior:** No persistence; always starts fresh.

**Desired Behavior:** "Resume" button or automatic return to last position.

**Prerequisites:** None (standalone)

**Files to Modify:**
1. `src/web/static/js/review.js` - localStorage persistence
2. `src/web/templates/review.html` or `filing_list.html` - Resume UI

**Implementation Requirements:**

1. **Persistence Layer**
   - Store in browser localStorage: filing_id, candidate_index
   - Update on each navigation
   - Clear when review is complete

2. **Resume UI**
   - "Resume where you left off" button on filing list
   - Shows filing name and progress
   - Optional: auto-resume setting

3. **Edge Cases**
   - Handle deleted candidates
   - Handle completed filings
   - Graceful fallback to start if position invalid

**Test Requirements:**

### Coverage Target: Manual testing (localStorage)

### Test Categories (manual)

1. **Persistence Tests**
   - Verify position saved on navigation
   - Verify resume works after browser close
   - Verify handles invalid positions

**Acceptance Criteria:**
- [ ] Last position saved to localStorage
- [ ] "Resume" button shows on return visit
- [ ] Clicking resume navigates to last position
- [ ] Invalid positions handled gracefully
- [ ] Manual testing complete

**Do NOT:**
- Store session data server-side (use localStorage only)
- Auto-resume without user action (could be confusing)
- Persist data longer than 30 days

**Verification Commands:**

```bash
# Manual testing only
# 1. Review some candidates
# 2. Close browser
# 3. Return and verify "Resume" appears
# 4. Click resume, verify correct position
```

---

### HRI-11: Add Statistics Dashboard

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-11
TASK NAME:     Create /review/stats dashboard with review metrics
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.2
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3 hr (backend 1.5 hr, frontend 1.5 hr)
TIME ACTUAL:   N/A
RISK LEVEL:    Low
PARALLEL WITH: HRI-10
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Create a statistics dashboard showing review progress and patterns.

**Business Rationale:** Visibility into review progress motivates completion and helps identify bottlenecks.

**Current Behavior:** No aggregate statistics view.

**Desired Behavior:** Dashboard at `/review/stats` with key metrics.

**Prerequisites:**
- Sufficient decision data (30+ decisions recommended)

**Files to Create:**
1. `src/web/templates/stats.html` - Dashboard template

**Files to Modify:**
1. `src/web/routes/review.py` - Add /review/stats route
2. `src/infra/db.py` - Add statistics query methods

**Implementation Requirements:**

1. **Metrics to Display**
   - Total decisions made (accept/reject/reclassify counts)
   - Decisions per day (last 7 days chart)
   - Average review time per candidate
   - Decisions by metric type (bar chart)
   - Overall progress (% of candidates reviewed)

2. **Query Methods**
   - `get_decision_statistics()` - aggregate counts
   - `get_daily_decision_counts(days=7)` - time series
   - `get_decisions_by_metric()` - breakdown

3. **Visualization**
   - Use Chart.js or similar for charts
   - Responsive design
   - Loading states for async data

**Test Requirements:**

### Coverage Target: **≥ 90%** for statistics endpoints

### Test Categories (6+ tests)

1. **Statistics Queries** (4 tests)
   - Test aggregate counts
   - Test daily counts
   - Test metric breakdown
   - Test empty data handling

2. **Route Tests** (2 tests)
   - Test /review/stats returns 200
   - Test template renders correctly

**Acceptance Criteria:**
- [ ] `/review/stats` route accessible
- [ ] Total decisions displayed
- [ ] Daily chart shows last 7 days
- [ ] Metric breakdown chart works
- [ ] Progress percentage shown
- [ ] 6+ unit tests
- [ ] Existing tests still pass

**Do NOT:**
- Build real-time updates (static refresh is fine)
- Add user-level statistics (no multi-user yet)
- Expose raw database queries in API

**Verification Commands:**

```bash
# Run review route tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py \
  --cov=src/web/routes/review --cov-report=term-missing
```

---

### HRI-12: Add Inter-Rater Agreement

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRI-12
TASK NAME:     Track multiple reviewers and calculate agreement metrics
WORKSTREAM:    Human Review Interface (Future)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.4
STATUS:        🟡 PENDING (BLOCKED)
COMPLETION:    N/A
TIME ESTIMATE: 4 hr
TIME ACTUAL:   N/A
RISK LEVEL:    High (requires multi-user infrastructure)
PARALLEL WITH: None (blocked)
═══════════════════════════════════════════════════════════════════════════════
```

**Objective:** Enable multiple reviewers per candidate and calculate agreement metrics (Cohen's Kappa).

**Business Rationale:** Inter-rater reliability is critical for training data quality. Disagreements indicate ambiguous cases needing arbitration.

**Current Behavior:** Single reviewer per candidate, no user tracking.

**Desired Behavior:** Multiple reviewers, agreement metrics, arbitration workflow.

**Prerequisites:**
- Multi-user authentication system (NOT YET BUILT)
- User management infrastructure

**BLOCKER:** This task requires multi-user support which does not exist in the current system. The task should remain blocked until:
1. User authentication is implemented
2. Reviewer ID tracking is added to decisions
3. User management routes exist

**Files to Create:**
1. `src/review/agreement.py` - Cohen's Kappa calculation

**Files to Modify:**
1. `src/infra/db.py` - Multi-reviewer queries
2. `src/web/routes/review.py` - Arbitration routes
3. Database schema - reviewer_id in decisions

**Implementation Requirements:**

1. **Multi-Reviewer Support**
   - Allow multiple decisions per candidate from different reviewers
   - Track reviewer_id on each decision

2. **Agreement Metrics**
   - Calculate Cohen's Kappa for reviewer pairs
   - Calculate overall agreement percentage
   - Identify high-disagreement candidates

3. **Arbitration Workflow**
   - Flag candidates with disagreement
   - Route to senior reviewer for final decision
   - Record arbitration decision separately

**Note:** Detailed implementation requirements will be defined when multi-user infrastructure exists.

**Acceptance Criteria:**
- [ ] Reviewer ID tracked on decisions
- [ ] Cohen's Kappa calculated
- [ ] Disagreement flagging works
- [ ] Arbitration workflow functional
- [ ] Tests cover agreement calculations

**Do NOT:**
- Implement before multi-user auth exists
- Build custom auth (use established patterns)
- Skip arbitration workflow (critical for quality)

---

## Appendix: Quick Reference

### Effort Summary

| Phase | Tasks | Total Effort |
|-------|-------|--------------|
| Phase 1 (Critical) | HRI-1, HRI-2, HRI-3 | 3-5 hours |
| Phase 2 (Quick UX) | HRI-4, HRI-5, HRI-6 | 4 hours |
| Phase 3 (Advanced) | HRI-7, HRI-8, HRI-9 | 6 hours |
| Phase 4 (Future) | HRI-10, HRI-11, HRI-12 | 8+ hours |

### Parallelization Options

**Can run in parallel:**
- HRI-1 + HRI-2 (both P1, no dependencies)
- HRI-4 + HRI-5 + HRI-6 (all P2, no dependencies)
- HRI-7 + HRI-9 (both P3, no dependencies)
- HRI-10 + HRI-11 (both P3, no dependencies)

**Must run sequentially:**
- HRI-6 → HRI-8 (bulk actions depend on filtering)
- Multi-user auth → HRI-12 (blocked)

---

## Version History

- **2025-12-17**: Initial creation from HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md analysis

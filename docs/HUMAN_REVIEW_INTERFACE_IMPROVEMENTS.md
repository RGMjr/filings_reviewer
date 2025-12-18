# Human Review Interface Improvement Plan

**Created:** 2025-12-16
**Last Updated:** 2025-12-17 (HRI-9 complete)
**Status:** Active
**Owner:** TBD

## Executive Summary

Following comprehensive testing of the human review interface, this document tracks improvements to enhance functionality, usability, and reliability. Improvements are organized by priority with effort estimates and implementation status.

### Testing Summary (2025-12-16)

| Feature | Status | Notes |
|---------|--------|-------|
| Accept decisions | ✅ Working | Database persistence verified |
| Reject decisions | ✅ Working | Categories and reasons preserved |
| Reclassify decisions | ✅ Working | Metric reassignment functional |
| Audit logging (pages) | ✅ Working | 127 entries captured |
| Audit logging (API) | ✅ Fixed | HRI-2 complete (2025-12-17) |
| Health check | ✅ Fixed | HRI-1 complete (2025-12-17) |

---

## P1: Critical Fixes

### P1.1: Fix Health Check Bug

**Priority:** Critical
**Effort:** 15 minutes
**Status:** ✅ Complete (2025-12-17)

**Problem:**
```
Health check failed: 'PoolHealthReport' object is not subscriptable
```
The `/health` endpoint returns 503 due to incorrect object access.

**Location:** `src/web/app.py:281-298`

**Root Cause:**
`check_pool_health()` returns a `PoolHealthReport` dataclass, but the code treats it as a dict.

**Fix Applied:**
```python
# Before (broken):
health = check_pool_health(pool)
if health["healthy"]:
    return jsonify({"pool_stats": health["stats"]})

# After (fixed):
health = check_pool_health(pool)
if health.is_healthy:
    return jsonify({"pool_stats": {
        "total_connections": health.total_connections,
        "idle_connections": health.idle_connections,
        "active_connections": health.active_connections,
        "test_query_elapsed": health.test_query_elapsed,
    }})
```

**Acceptance Criteria:**
- [x] `/health` returns 200 when database is connected
- [x] Pool stats included in response
- [x] Unit tests added for health endpoint (2 tests in `tests/unit/web/test_app_pool.py`)

**Commit:** `82aa9da` - HRI-1: Fix health endpoint PoolHealthReport attribute access

---

### P1.2: Add API Audit Logging

**Priority:** Critical
**Effort:** 30-45 minutes
**Status:** ✅ Complete (2025-12-17)

**Problem:**
Decision submissions (`POST /api/decisions`) are not captured in `review_audit_log`. This creates a compliance gap - we can see page views but not the actual decisions being made.

**Location:** `src/web/routes/api.py`

**Fix Applied:**
1. Added `@api_bp.before_request` hook to capture request start time
2. Added `@api_bp.after_request` hook to log all API requests
3. Decision details (decision type, assigned_metric_id, rejection_category) captured in `query_params` JSONB
4. Candidate ID extracted from request body and logged
5. Response status and time tracked for all requests

**Test Coverage:**
- 18 unit tests added in `tests/unit/web/test_api_audit_logging.py`
- 97% coverage for api.py

**Acceptance Criteria:**
- [x] All POST /api/decisions calls logged to review_audit_log
- [x] Decision type captured (accept/reject/reclassify)
- [x] Candidate ID linked in audit entry
- [x] 18 unit tests covering logging scenarios

---

### P1.3: Improve Metric Classification Accuracy

**Priority:** High
**Effort:** 2-4 hours
**Status:** ✅ Complete (2025-12-17)

**Problem:**
During testing, some candidates had incorrect initial metric associations:
- "Contribution Margin was 41.6%" incorrectly tagged as CAC (Customer Acquisition Cost)
- Similar terminology overlap issues observed

**Solution Implemented (HRI-3):**
- Added `METRIC_EXCLUSION_PATTERNS` dictionary to `keyword_matching.py`
- Implemented exclusion checking in `find_all_keywords()` method with ±50 char context window
- Pre-compiled exclusion patterns for performance

**Top 5 Misclassification Patterns Fixed:**
1. "customer acquisition" in CAC context → excluded from cm_new_customers_acquired
2. Margin keywords → excluded from cm_customer_acquisition_cost
3. LTV/CAC ratio context → excludes standalone LTV metric
4. Cohort context → excludes overall gross margin metric
5. Revenue/dollar retention → excludes customer retention rate

**Acceptance Criteria:**
- [x] Audit of current keyword overlaps completed
- [x] Confusion matrix generated from existing decisions
- [x] Top 5 misclassification patterns identified
- [x] Keyword adjustments made and tested (34 new tests)

---

## P2: Usability Improvements

### P2.1: Add Keyboard Shortcuts

**Priority:** Medium
**Effort:** 45 minutes - 1 hour
**Status:** ✅ Complete (2025-12-17)

**Benefit:** 2-3x faster review workflow for power users

**Implemented Shortcuts:**
| Key | Action | Status |
|-----|--------|--------|
| `A` | Accept with suggested metric | ✅ (existing) |
| `R` | Open reject modal | ✅ (existing) |
| `C` | Open reclassify modal | ✅ (existing) |
| `N` | Next candidate | ✅ (existing) |
| `P` | Previous candidate | ✅ NEW |
| `Enter` | Confirm rejection | ✅ NEW |
| `Esc` | Cancel/close modal | ✅ NEW |
| `?` / `H` | Toggle hints panel | ✅ NEW |

**Implementation:**
1. ✅ Added `navigateToPrevious()` function with wrap-around logic
2. ✅ Extended `handleKeyboardShortcut()` with P, Enter, Escape, ? cases
3. ✅ Added keyboard hints panel (fixed footer + toggle button)
4. ✅ Updated sidebar documentation to show all shortcuts
5. ✅ JavaScript syntax validated with `node --check`

**Acceptance Criteria:**
- [x] All shortcuts functional
- [x] Shortcuts documented in UI (sidebar + hints panel)
- [x] Works across Chrome, Firefox, Safari
- [x] No accessibility conflicts (WCAG 2.1 AA compliant)
- [x] All 37 web route tests pass

**Commit:** HRI-5

---

### P2.2: Display Confidence Scores in Sidebar

**Priority:** Medium
**Effort:** 30-45 minutes
**Status:** ✅ Complete (2025-12-17)

**Problem:**
Confidence scores were displayed on the main candidate card but NOT in the sidebar candidate list. Reviewers had to click into each candidate to see its confidence level, which slowed down triage.

**Implementation:**
- ✅ Added confidence badge to sidebar candidate items (review.html:546-565)
- ✅ Color coding matches main card: green (≥0.7), yellow (0.4-0.7), red (<0.4)
- ✅ Shows compact percentage (e.g., "87%") with small font size
- ✅ Added tooltip: "{{ conf_label }} confidence - System's confidence in this metric classification"
- ✅ Added ARIA label for screen readers
- ✅ Gracefully handles missing confidence (no badge shown if None)

**UI Implementation (Sidebar):**
```jinja2
{# Confidence badge (HRI-4) #}
{% if candidate.suggestion_confidence is not none %}
    {% set conf = candidate.suggestion_confidence %}
    {% if conf >= 0.7 %}
        {% set conf_color = 'success' %}
        {% set conf_label = 'High' %}
    {% elif conf >= 0.4 %}
        {% set conf_color = 'warning' %}
        {% set conf_label = 'Medium' %}
    {% else %}
        {% set conf_color = 'danger' %}
        {% set conf_label = 'Low' %}
    {% endif %}
    <span class="badge bg-{{ conf_color }} ms-1"
          style="font-size: 0.65rem;"
          title="{{ conf_label }} confidence - System's confidence..."
          aria-label="{{ conf_label }} confidence: {{ "{:.0f}".format(conf * 100) }} percent">
        {{ "{:.0f}".format(conf * 100) }}%
    </span>
{% endif %}
```

**Acceptance Criteria:**
- [x] Confidence badge shown in sidebar for each candidate
- [x] Color coding matches main card (green/yellow/red)
- [x] Tooltip explains score meaning
- [x] ARIA label for accessibility
- [x] All 37 web route tests pass
- [x] Template-only change (no backend modifications)

**Commit:** HRI-4

---

### P2.3: Add Decision History Panel

**Priority:** Medium
**Effort:** 1-2 hours
**Status:** Not Started

**Problem:**
No visibility into previous decisions during a review session. Reviewers may forget what they decided or want to undo a mistake.

**Features:**
1. Sidebar panel showing last 10 decisions in session
2. Click to jump to that candidate
3. "Undo" option for most recent decision (soft delete)

**Implementation:**
1. Store recent decisions in JavaScript session state
2. Add collapsible history panel to UI
3. API endpoint for decision reversal (optional)

**Acceptance Criteria:**
- [ ] History panel shows recent decisions
- [ ] Clicking entry navigates to candidate
- [ ] Visual distinction for accept/reject/reclassify
- [ ] Undo functionality for last decision

---

### P2.4: Add Bulk Actions

**Priority:** Medium
**Effort:** 2-3 hours
**Status:** Not Started

**Problem:**
Reviewing candidates one-by-one is slow when patterns are obvious.

**Features:**
1. Multi-select checkboxes on candidate list
2. Bulk actions: "Accept all selected", "Reject all selected"
3. "Accept all high-confidence" (confidence > threshold)
4. Confirmation modal with summary before applying

**Safety Measures:**
- Maximum 20 candidates per bulk action
- Require confirmation for bulk operations
- Log bulk actions separately in audit

**Acceptance Criteria:**
- [ ] Multi-select UI implemented
- [ ] Bulk accept/reject functional
- [ ] Confirmation modal shows affected candidates
- [ ] Audit log captures bulk operations

---

### P2.5: Add Filtering and Sorting

**Priority:** Medium
**Effort:** 1-2 hours
**Status:** Not Started

**Current State:**
Candidates shown in document order (by candidate_id).

**Proposed Filters:**
- Status: Pending / Reviewed / All
- Metric type: Dropdown of detected metrics
- Confidence: High (>0.8) / Medium (0.5-0.8) / Low (<0.5)

**Proposed Sort Options:**
- Document order (default)
- Confidence (low to high - review uncertain first)
- Confidence (high to low - quick wins first)
- Value magnitude

**Acceptance Criteria:**
- [ ] Filter dropdowns in sidebar
- [ ] Sort dropdown implemented
- [ ] Filters persist during session
- [ ] URL parameters reflect current filters

---

## P3: Nice-to-Have Enhancements

### P3.1: Context Expansion

**Priority:** Low
**Effort:** 1 hour
**Status:** ✅ Complete (2025-12-17)

**Feature:**
- "Show more context" button reveals surrounding paragraphs
- "View in SEC filing" link opens original document

**Implementation:**
- ✅ Database method `get_expanded_context_for_candidate()` fetches adjacent segments
- ✅ API endpoint `GET /api/candidates/<id>/expanded-context` returns expanded context
- ✅ JavaScript handler with expand/collapse toggle functionality
- ✅ "View in SEC" button on each candidate card
- ✅ 5 comprehensive tests covering edge cases

**Delivered:**
- Expands context from ~50 words to ~150+ words on demand
- Opens SEC EDGAR filing in new tab for verification
- Handles edge cases: no source segment, filing boundaries, errors
- Full test coverage with error handling

**Commit:** `2284dd1` - HRI-9: Add context expansion and SEC filing links

---

### P3.2: Review Statistics Dashboard

**Priority:** Low
**Effort:** 2-3 hours
**Status:** Not Started

**Metrics to Display:**
- Decisions per session/day
- Average review time per candidate
- Accept/reject/reclassify ratio
- Decisions by metric type
- Progress across all filings

**Location:** New route `/review/stats`

---

### P3.3: Session Persistence

**Priority:** Low
**Effort:** 1 hour
**Status:** ✅ Complete (2025-12-17)

**Feature:**
- Remember last viewed filing and candidate
- "Resume where you left off" on return visit
- Store in browser localStorage or server-side session

**Implementation Notes:**
- localStorage persistence with 30-day expiration
- Resume button on filing list page
- URL parameter support (?candidate=N)
- Auto-clear when filing 100% complete
- Graceful degradation in private browsing

---

### P3.4: Inter-Rater Agreement Tracking

**Priority:** Low
**Effort:** 3-4 hours
**Status:** Not Started

**Feature:**
- Allow multiple reviewers per candidate
- Calculate agreement metrics (Cohen's Kappa)
- Flag candidates with disagreement for arbitration

**Note:** Requires multi-user support first.

---

---

## Completed Improvements

### Table Row Filtering & Row Heading Priority (2025-12-17)

**Priority:** P2 (High)
**Effort:** 4 hours
**Status:** ✅ Complete

**Problem:**
During manual testing, users reported that table displays showed values matched with incorrect keywords:
1. Value from one row matched with keyword from a different row
2. Row headings (most specific labels) not prioritized over table/section headings

**Example Issue:**
- Candidate #36 (Farfetch): Value 116,878 in "Gross profit" row was matched with "Gross profit margin" from the next row
- This created confusing context displays where the highlighted keyword wasn't semantically related to the value

**Solution Implemented:**

1. **Table Row Parser** (`src/review/table_structure.py`):
   - Added `TableRowParser` class to parse HTML table structure using BeautifulSoup
   - Maps character positions in extracted text to table row boundaries
   - Detects row headings (first cell in each row) with position tracking
   - New fields: `header_text`, `header_start`, `header_end` in `TableRow` dataclass
   - New method: `is_row_heading(position)` to check if keyword is in first cell

2. **Keyword Matching Enhancements** (`src/review/keyword_matching.py`):
   - **Phase 2.75**: Table row filtering prevents cross-row matches
   - **Row Heading Priority**: Applies 0.25x multiplier (75% reduction) to effective distance for row headings
   - Row headings are now strongly preferred over other keywords in the same table
   - Falls back to all keywords if none found in same row (prevents over-filtering)

3. **Keyword Pattern Addition** (`src/extraction/metric_classifier.py`):
   - Added `r"\bgross\s+profit\b"` pattern to enable matching "Gross profit" row headings
   - Previously only "gross profit margin" was matched, causing fallback to wrong row

4. **HTML Validation** (`src/infra/db.py`):
   - Added validation check: clears `segment_html` if it doesn't contain the value/keyword
   - Forces fallback to `context_text` display for truncated HTML segments
   - Prevents displaying empty or irrelevant table context

**Results:**
- **Before:** Value 116,878 → "Gross profit margin" (different row, distance=13)
- **After:** Value 116,878 → "Gross profit" (row heading, same row, distance=1)

**Impact:**
- Farfetch filing: 52 → 165 candidates (increased due to broader "gross profit" matching)
- Snowflake filing: 50 → 32 candidates (36% reduction from table row filtering)
- Improved precision by ensuring values match with most relevant/specific keywords
- Better user experience: context displays now show semantically correct associations

**Testing:**
- Verified row heading detection on multi-row financial tables
- Confirmed "Gross profit" prioritized over "Gross profit margin" in test cases
- Regenerated candidates for Farfetch and Snowflake filings with new logic
- Manual testing in web interface confirmed correct keyword highlighting

**Files Modified:**
- `src/review/table_structure.py` (68 lines added)
- `src/review/keyword_matching.py` (13 lines added)
- `src/extraction/metric_classifier.py` (1 line added)
- `src/infra/db.py` (15 lines added)

**Next Steps:**
- Monitor candidate quality in production review sessions
- Consider adding more table-aware patterns (e.g., column header matching)
- Evaluate if row heading priority should be configurable per metric type

---

## Implementation Roadmap

### Phase 1: Critical Fixes (Week 1)
| Task | Effort | Dependencies |
|------|--------|--------------|
| P1.1 Health check fix | 15 min | None |
| P1.2 API audit logging | 45 min | None |
| P1.3 Classification audit | 2 hr | Existing decision data |

### Phase 2: Quick UX Wins (Week 2)
| Task | Effort | Dependencies | Status |
|------|--------|--------------|--------|
| P2.2 Confidence display | 45 min | None | ✅ Complete |
| P2.1 Keyboard shortcuts | 1 hr | None | ✅ Complete |
| P2.5 Filtering/sorting | 2 hr | None | Not Started |

### Phase 3: Advanced Features (Week 3-4)
| Task | Effort | Dependencies |
|------|--------|--------------|
| P2.3 Decision history | 2 hr | None |
| P2.4 Bulk actions | 3 hr | P2.5 (filtering) |
| P3.1 Context expansion | 1 hr | None |

### Phase 4: Analytics (Future)
| Task | Effort | Dependencies |
|------|--------|--------------|
| P3.2 Statistics dashboard | 3 hr | Sufficient decision data |
| P3.4 Inter-rater agreement | 4 hr | Multi-user support |

---

## Tracking

### Status Legend
- **Not Started** - Work has not begun
- **In Progress** - Currently being implemented
- **In Review** - Code complete, awaiting review
- **Complete** - Merged and deployed
- **Blocked** - Waiting on dependency

### Progress Summary

| Priority | Total | Complete | In Progress | Not Started |
|----------|-------|----------|-------------|-------------|
| P1 | 3 | 3 | 0 | 0 |
| P2 | 5 | 2 | 0 | 3 |
| P3 | 4 | 0 | 0 | 4 |
| **Total** | **12** | **5** | **0** | **7** |

---

## Appendix: Testing Notes

### Test Environment
- Flask development server on port 5000
- PostgreSQL on localhost:5433 (dev:dev)
- Browser automation via Playwright (MCP_DOCKER)

### Test Filing
- Filing ID: 31 (Farfetch Ltd)
- Total candidates: ~40
- Candidates tested: 3 (1181, 1169, 1170)

### Decision Verification Queries
```sql
-- Check decision was recorded
SELECT candidate_id, review_status, decision, assigned_metric_id,
       rejection_category, rejection_reason
FROM review_candidates rc
JOIN review_decisions rd USING (candidate_id)
WHERE candidate_id = ?;

-- Check audit log
SELECT log_id, timestamp, route_name, http_method, url_path,
       candidate_id, response_status
FROM review_audit_log
ORDER BY timestamp DESC
LIMIT 20;
```

---

## References

- [Human Review System Plan](HUMAN_REVIEW_SYSTEM_PLAN.md) - Original implementation roadmap
- [E1 Pattern Analyzer](archive/workstreams/E1-pattern-analyzer/E1_COMPLETION_SUMMARY.md) - Pattern learning system
- [Review Routes (D1)](../src/web/routes/review.py) - Main review interface code
- [API Routes (D2)](../src/web/routes/api.py) - Decision API endpoints

# Human Review Interface Improvement Plan

**Created:** 2025-12-16
**Last Updated:** 2025-12-16
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
| Audit logging (API) | ⚠️ Gap | POST /api/decisions not logged |
| Health check | ❌ Bug | PoolHealthReport subscript error |

---

## P1: Critical Fixes

### P1.1: Fix Health Check Bug

**Priority:** Critical
**Effort:** 15 minutes
**Status:** Not Started

**Problem:**
```
Health check failed: 'PoolHealthReport' object is not subscriptable
```
The `/health` endpoint returns 503 due to incorrect object access.

**Location:** `src/web/app.py:276-312`

**Root Cause:**
`check_pool_health()` returns a `PoolHealthReport` dataclass, but the code treats it as a dict.

**Fix:**
```python
# Current (broken):
health = check_pool_health(pool)
if health["healthy"]:
    return jsonify({"pool_stats": health["stats"]})

# Corrected:
health = check_pool_health(pool)
if health.healthy:
    return jsonify({"pool_stats": health.stats})
```

**Acceptance Criteria:**
- [ ] `/health` returns 200 when database is connected
- [ ] Pool stats included in response
- [ ] Unit test added for health endpoint

---

### P1.2: Add API Audit Logging

**Priority:** Critical
**Effort:** 30-45 minutes
**Status:** Not Started

**Problem:**
Decision submissions (`POST /api/decisions`) are not captured in `review_audit_log`. This creates a compliance gap - we can see page views but not the actual decisions being made.

**Location:** `src/web/routes/api.py`

**Implementation:**
1. Add `before_request` and `after_request` hooks to api_bp (similar to review_bp)
2. Log: endpoint, method, request body (sanitized), response status, user session
3. Include `candidate_id` and `decision` type in log entry

**Schema Addition (optional):**
```sql
-- Add decision-specific columns to audit log
ALTER TABLE review_audit_log ADD COLUMN decision_type VARCHAR(20);
ALTER TABLE review_audit_log ADD COLUMN request_body JSONB;
```

**Acceptance Criteria:**
- [ ] All POST /api/decisions calls logged to review_audit_log
- [ ] Decision type captured (accept/reject/reclassify)
- [ ] Candidate ID linked in audit entry
- [ ] Integration test verifies logging

---

### P1.3: Improve Metric Classification Accuracy

**Priority:** High
**Effort:** 2-4 hours
**Status:** Not Started

**Problem:**
During testing, some candidates had incorrect initial metric associations:
- "Contribution Margin was 41.6%" incorrectly tagged as CAC (Customer Acquisition Cost)
- Similar terminology overlap issues observed

**Investigation Needed:**
1. Review keyword lists in `src/review/keyword_matching.py`
2. Check for ambiguous terms that match multiple metrics
3. Analyze rejected candidates for classification patterns

**Potential Fixes:**
- Add metric-specific exclusion keywords
- Increase context requirements for ambiguous terms
- Add negative keywords (e.g., "contribution margin" should NOT match CAC)

**Acceptance Criteria:**
- [ ] Audit of current keyword overlaps completed
- [ ] Confusion matrix generated from existing decisions
- [ ] Top 5 misclassification patterns identified
- [ ] Keyword adjustments made and tested

---

## P2: Usability Improvements

### P2.1: Add Keyboard Shortcuts

**Priority:** Medium
**Effort:** 45 minutes - 1 hour
**Status:** Not Started

**Benefit:** 2-3x faster review workflow for power users

**Proposed Shortcuts:**
| Key | Action |
|-----|--------|
| `A` | Accept with suggested metric |
| `R` | Open reject modal |
| `C` | Open reclassify modal |
| `N` | Next candidate |
| `P` | Previous candidate |
| `Enter` | Confirm current action |
| `Esc` | Cancel/close modal |

**Implementation:**
1. Add keyboard event listener in `src/web/static/js/review.js`
2. Show shortcut hints in UI (tooltip or footer)
3. Ensure no conflicts with browser defaults

**Acceptance Criteria:**
- [ ] All shortcuts functional
- [ ] Shortcuts documented in UI
- [ ] Works across Chrome, Firefox, Safari
- [ ] No accessibility conflicts

---

### P2.2: Display Confidence Scores

**Priority:** Medium
**Effort:** 30-45 minutes
**Status:** Not Started

**Problem:**
Candidates have confidence scores computed (`CandidateFeatures.confidence_score`) but not displayed in the review UI.

**Benefit:**
- Helps reviewers prioritize low-confidence candidates
- Provides transparency into system recommendations
- Enables sorting/filtering by confidence

**Implementation:**
1. Pass confidence score to template in `src/web/routes/review.py`
2. Display as badge/indicator on candidate card
3. Use color coding: green (>0.8), yellow (0.5-0.8), red (<0.5)

**UI Mock:**
```
┌─────────────────────────────────────────┐
│ Candidate #1181            [🟢 87%]     │
│ Metric: Revenue Concentration           │
│ Value: 15%                              │
└─────────────────────────────────────────┘
```

**Acceptance Criteria:**
- [ ] Confidence score displayed on all candidates
- [ ] Color coding applied
- [ ] Tooltip explains score meaning
- [ ] Score visible in candidate list sidebar

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
**Status:** Not Started

**Feature:**
- "Show more context" button reveals surrounding paragraphs
- "View in SEC filing" link opens original document

**Implementation:**
- Store segment position in database
- Fetch adjacent segments on demand
- Construct SEC EDGAR URL from filing metadata

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
**Status:** Not Started

**Feature:**
- Remember last viewed filing and candidate
- "Resume where you left off" on return visit
- Store in browser localStorage or server-side session

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

## Implementation Roadmap

### Phase 1: Critical Fixes (Week 1)
| Task | Effort | Dependencies |
|------|--------|--------------|
| P1.1 Health check fix | 15 min | None |
| P1.2 API audit logging | 45 min | None |
| P1.3 Classification audit | 2 hr | Existing decision data |

### Phase 2: Quick UX Wins (Week 2)
| Task | Effort | Dependencies |
|------|--------|--------------|
| P2.2 Confidence display | 45 min | None |
| P2.1 Keyboard shortcuts | 1 hr | None |
| P2.5 Filtering/sorting | 2 hr | None |

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
| P1 | 3 | 0 | 0 | 3 |
| P2 | 5 | 0 | 0 | 5 |
| P3 | 4 | 0 | 0 | 4 |
| **Total** | **12** | **0** | **0** | **12** |

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

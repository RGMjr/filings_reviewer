# WORKER PROMPT: Task HRI-10 - Add Session Persistence

```
===============================================================================
TASK ID:       HRI-10
TASK NAME:     Remember last viewed filing/candidate for "resume where left off"
WORKSTREAM:    Human Review Interface (Nice-to-Have)
SOURCE:        HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.3
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1 hr (localStorage logic 30 min, UI 20 min, edge cases 10 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None
PARALLEL WITH: HRI-9, HRI-11 (all independent P3 tasks)
===============================================================================
```

## Objective

Implement browser-side session persistence so reviewers can resume where they left off after closing the browser or navigating away.

**Business Rationale**: Reviewers often work in multiple sessions across days. Without position persistence, they waste time scrolling through already-reviewed candidates to find where they stopped. This is especially painful for filings with 50+ candidates.

**Current Behavior**: No persistence; browser refresh or return always starts at first candidate.

**Desired Behavior**:
- Last viewed filing ID and candidate index automatically saved to localStorage
- "Resume where you left off" button appears on filing list when saved position exists
- Clicking resume navigates directly to the saved candidate

## Prerequisites

- None (standalone task)
- Familiarity with review.html and filing_list.html templates
- Understanding of JavaScript localStorage API

## Files to Modify

1. **`src/web/static/js/review.js`** - Add localStorage save/load logic
2. **`src/web/templates/review.html`** - Save position on candidate navigation
3. **`src/web/templates/filing_list.html`** - Add "Resume" button with saved position info

## Files to Read (Context Only)

- `src/web/templates/review.html` - Current candidate navigation structure
- `src/web/templates/filing_list.html` - Filing list page structure
- `src/web/static/js/review.js` - Existing keyboard navigation (HRI-5, HRI-7)
- Recent HRI commits for established UI patterns

## Implementation Requirements

### 1. localStorage Persistence Layer

- **Storage Key**: `reviewProgress` (JSON object)
- **Data Structure**:
  ```javascript
  {
    filingId: number,          // Current filing being reviewed
    candidateIndex: number,    // 0-based index of current candidate
    candidateId: number,       // ID for validation
    filingName: string,        // Display name for resume button
    lastUpdated: ISO timestamp // For expiration check
  }
  ```
- **Save Trigger**: Update on every candidate navigation (selectCandidate, navigateToNext, navigateToPrevious)
- **Clear Triggers**:
  - When all candidates in filing are reviewed (100% complete)
  - When user explicitly clicks "Start fresh" or similar
  - When data is older than 30 days

### 2. Resume UI on Filing List

- **Location**: Add section above or within the filing list on `filing_list.html`
- **Display Conditions**:
  - Only show if localStorage has valid saved position
  - Only show if saved filing still exists and has pending candidates
- **UI Elements**:
  - Prominent "Resume where you left off" button/card
  - Filing name and progress indicator (e.g., "Farfetch Ltd - 15/52 reviewed")
  - "Start fresh" link to clear saved position
- **Action**: Clicking resume navigates to `/review/filings/{filing_id}?candidate={index}`

### 3. URL Parameter Support

- **Parameter**: `?candidate={index}` on review page
- **Behavior**: If URL has `candidate` param, auto-select that candidate on page load
- **Implementation**: Check URL params in review.js `DOMContentLoaded`, call `selectCandidate(index)`
- **Validation**: If index is out of bounds, fall back to first unreviewed candidate

### 4. Edge Cases

- **Deleted/completed filing**: Check filing status before showing resume; clear localStorage if invalid
- **Candidate out of range**: If saved index exceeds candidate count, navigate to last candidate
- **Already 100% reviewed**: Don't show resume for completed filings; clear saved position
- **Multiple tabs**: Last-write-wins is acceptable (no need for cross-tab sync)
- **Graceful degradation**: If localStorage unavailable (private browsing), feature silently disabled

### Error Handling

- **localStorage unavailable**: Wrap all localStorage access in try/catch; feature disabled if unavailable
- **Invalid JSON**: Clear corrupted data and start fresh
- **Stale data (>30 days)**: Treat as no saved position

## Test Requirements

### Coverage Target: Manual testing (JavaScript/localStorage)

Automated unit tests are not practical for localStorage behavior. Focus on manual testing checklist.

### Manual Testing Checklist (8 scenarios)

1. **Save on Navigation**
   - [ ] Navigate through candidates; verify localStorage updates each time
   - [ ] Refresh browser; verify can resume at same position

2. **Resume Button Display**
   - [ ] Close browser, return to filing list; verify "Resume" button appears
   - [ ] Verify filing name and progress shown correctly
   - [ ] Verify resume button not shown if no saved position

3. **Resume Navigation**
   - [ ] Click resume; verify navigates to correct filing and candidate
   - [ ] Verify URL includes `?candidate=N` parameter

4. **Clear on Completion**
   - [ ] Review all candidates in a filing; verify localStorage cleared
   - [ ] Verify resume button disappears after completion

5. **Edge Cases**
   - [ ] Delete saved filing from database; verify graceful handling
   - [ ] Set candidate index beyond actual count; verify fallback behavior
   - [ ] Clear localStorage manually; verify no errors

6. **Expiration**
   - [ ] Set lastUpdated to 31 days ago; verify position not resumed

7. **Start Fresh**
   - [ ] Click "Start fresh" link; verify localStorage cleared
   - [ ] Verify resume button disappears

8. **Cross-Browser**
   - [ ] Test in Chrome, Firefox, Safari
   - [ ] Test in private/incognito mode (should silently disable)

## Acceptance Criteria

- [ ] Position (filing ID + candidate index) saved to localStorage on each navigation
- [ ] "Resume where you left off" button appears on filing list when valid position exists
- [ ] Button shows filing name and review progress
- [ ] Clicking resume navigates to saved position via URL parameter
- [ ] URL parameter `?candidate=N` supported on review page
- [ ] Position cleared when filing review is complete (100%)
- [ ] "Start fresh" option clears saved position
- [ ] Data expires after 30 days of inactivity
- [ ] Graceful handling of edge cases (deleted filing, out-of-range index)
- [ ] No errors in private browsing mode (feature disabled gracefully)
- [ ] JavaScript syntax valid (`node --check src/web/static/js/review.js`)
- [ ] All existing tests still pass
- [ ] Manual testing checklist complete

## Do NOT

- Store session data server-side (use localStorage only, not database)
- Auto-resume without user action (could be confusing if user wanted to start fresh)
- Persist data longer than 30 days (to avoid stale positions)
- Add complex cross-tab synchronization (last-write-wins is acceptable)
- Break existing review navigation functionality
- Add new Python dependencies
- Modify database schema

## Verification Commands

```bash
# Check JavaScript syntax
node --check src/web/static/js/review.js

# Run all web tests to ensure no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/ tests/integration/web/ -v --tb=short

# Manual testing required for localStorage functionality
# See "Manual Testing Checklist" above
```

## Expected Impact

**Before HRI-10**:
- Reviewers lose position on browser close/refresh
- Must scroll through all candidates to find where they stopped
- Frustrating for filings with 50+ candidates

**After HRI-10**:
- One-click resume from filing list
- Position automatically tracked
- Seamless multi-session review workflow

## Post-Implementation Tasks

After completing HRI-10:

1. **Update Documentation**:
   - Mark HRI-10 as COMPLETE in `docs/HUMAN_REVIEW_SYSTEM_TASKS.md`
   - Update `docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md` P3.3 status
   - Add implementation notes (commit hash, any deviations from plan)

2. **Archive**:
   - Move this file to `docs/archive/workstreams/HRI-interface/WORKER_PROMPT_TASK_HRI-10.md`

3. **Commit and Push**:
   ```bash
   git add src/web/static/js/review.js \
           src/web/templates/review.html \
           src/web/templates/filing_list.html \
           docs/HUMAN_REVIEW_SYSTEM_TASKS.md \
           docs/HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md
   git commit -m "HRI-10: Add session persistence for review progress

   - Save current filing/candidate position to localStorage on navigation
   - Add 'Resume where you left off' button to filing list page
   - Support ?candidate=N URL parameter for direct navigation
   - Auto-clear position when filing review is 100% complete
   - 30-day expiration for stale positions

   Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"
   git push origin main
   ```

## Reference

- **Issue source**: HUMAN_REVIEW_INTERFACE_IMPROVEMENTS.md P3.3
- **Dependencies**: None
- **Related tasks**: HRI-9 (Context Expansion), HRI-11 (Statistics Dashboard)
- **Completed prerequisites**: HRI-7 (Decision History - established session state patterns)

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)

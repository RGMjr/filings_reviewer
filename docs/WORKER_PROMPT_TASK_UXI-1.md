# WORKER PROMPT: Task UXI-1 - Dropdown Keyboard Navigation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-1
TASK NAME:     Add keyboard navigation to dropdown menus (number keys + arrows)
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3h (breakdown: investigation 30 min, implementation 90 min, testing 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (additive JavaScript changes, no backend modifications)
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       UXI-4
BLOCKS:        None
PARALLEL WITH: UXI-2, UXI-3
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Enable keyboard-only navigation within dropdown menus after they're opened via shortcuts (`R` for reject, `C` for reclassify).

**Business Rationale**: Reviewers using keyboard shortcuts are forced to use mouse for dropdown selection, breaking workflow and adding 3-5 seconds per decision.

**Current Behavior**: Pressing `R` or `C` opens dropdown, but user must click to select. Arrow keys don't work. No number shortcuts for rejection categories.

**Desired Behavior**: After `R`, user presses `1-6` for rejection category. Arrow keys navigate both dropdowns. `Enter` confirms, `Escape` cancels. Visual focus indicator shows current selection.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/web/static/js/review.js`** - Add dropdown keyboard navigation handlers

## Files to Read (Context Only)

- `src/web/templates/review.html` - Understand dropdown structure (lines 580-628)

## Implementation Requirements

### Core Functionality

1. **Number Key Shortcuts for Rejection Categories**
   - Map `1-6` to rejection categories: Wrong Metric, Not a Metric, Wrong Value, Wrong Period, Duplicate, Other
   - Only active when rejection dropdown is open
   - Trigger same handler as clicking category

2. **Arrow Key Navigation**
   - `ArrowDown`/`ArrowUp`: Move focus with wrap-around
   - Works for both rejection and reclassify dropdowns
   - Visual focus indicator (`.active` class or outline)

3. **Keyboard Confirmation**
   - `Enter`: Select focused item and close dropdown
   - `Escape`: Close without selection

4. **State Management**
   - Track active dropdown (rejection vs reclassify vs null)
   - Track focused index within dropdown
   - Reset state when dropdown closes

5. **Update Keyboard Hints**
   - Update hints panel to show `1-6` shortcuts after Reject

### Error Handling

- **Dropdown not open**: Number/arrow keys do nothing
- **Empty dropdown**: No-op
- **Focus in text field**: Ignore shortcuts

## Test Requirements

### Coverage Target: **Manual testing** (client-side JavaScript)

### Test Scenarios (8+ manual tests)

1. Press `R`, press `1` - select "Wrong Metric Type"
2. Press `R`, `ArrowDown` twice, `Enter` - select 3rd item
3. Press `R`, `Escape` - close without selection
4. Press `C`, navigate with arrows, `Enter` - select metric
5. `ArrowDown` at last item wraps to first
6. `ArrowUp` at first item wraps to last
7. Number keys when no dropdown open - no effect
8. Typing in textarea, press `1` - types "1", not shortcut

## Acceptance Criteria

- [ ] Number keys `1-6` select rejection categories when dropdown open
- [ ] Arrow keys navigate both dropdowns with visible focus indicator
- [ ] `Enter` confirms selection, `Escape` cancels
- [ ] Keyboard hints panel updated with new shortcuts
- [ ] Number keys do NOT trigger when typing in text fields
- [ ] Arrow keys do NOT interfere with page scroll when dropdown closed
- [ ] All existing shortcuts still work (A, F, R, C, N, P)
- [ ] Works in Chrome, Firefox, Safari

## Do NOT

- Modify any Python backend code
- Change dropdown HTML structure
- Remove or modify existing keyboard shortcuts
- Add external dependencies
- Modify `review.html` template (except comments)

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug

# Manual testing in browser - see Test Scenarios above
```

## Critical Evaluation Phase

**Required for all tasks. Depth: Standard (M task)**

After verification passes but BEFORE committing:
1. Code Quality Review - Check for linting issues, DRY violations
2. Test Coverage Assessment - Verify all scenarios tested manually
3. Architecture Alignment - Ensure follows existing JS patterns in review.js
4. Identify Improvements - Note any optimizations or edge cases
5. **User Approval (REQUIRED)** - STOP and ask before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for deferred improvements
8. Commit and Push

## Reference

- **Issue source**: UI/UX Review (2026-01-06)
- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`
- **Related**: UXI-2 (Metric Dropdown Search), HRI-5 (Original keyboard shortcuts)

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

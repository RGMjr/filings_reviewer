# WORKER PROMPT: Task UXI-1a - Fix Arrow Key + Enter Selection in Dropdowns

```
===============================================================================
TASK ID:       UXI-1a
TASK NAME:     Fix arrow key navigation state synchronization in dropdown menus
WORKSTREAM:    UX Improvements
SOURCE:        UXI-1 Playwright testing (2026-01-07)
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2h (breakdown: investigation 15 min, implementation 45 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (additive JavaScript changes, no backend modifications)
TASK SIZE:     S
DEPENDS ON:    None (UXI-1 core functionality already implemented)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-2, UXI-3, UXI-4
===============================================================================
```

## Objective

Fix the bug where arrow key navigation in dropdown menus does not properly sync with internal state, causing Enter key to select the wrong item.

**Business Rationale**: Users navigating rejection/reclassify dropdowns with arrow keys expect Enter to select the visually focused item. Currently, Enter selects a stale item because Bootstrap intercepts arrow events before our custom handler can update `state.dropdownFocusIndex`.

**Current Behavior**:
1. Press `R` to open reject dropdown - first item shows focus
2. Press ArrowDown - visual focus moves to second item (Bootstrap handles this)
3. Press Enter - WRONG: selects first item (or nothing) because `state.dropdownFocusIndex` is stale
4. Console shows: `Selected dropdown item: -1` (should be 1)

**Desired Behavior**:
1. Press `R` to open reject dropdown - first item shows focus
2. Press ArrowDown - visual focus moves AND internal state updates
3. Press Enter - CORRECT: selects the visually focused item
4. Console shows: `Selected dropdown item: 1`

## Prerequisites

- None (standalone fix for existing UXI-1 implementation)

## Files to Modify

1. **`src/web/static/js/review.js`** - Fix dropdown keyboard navigation state sync

## Files to Read (Context Only)

- `src/web/templates/review.html` - Understand dropdown HTML structure (lines 594-642)

## Implementation Requirements

### Core Functionality

1. **Fix Enter Key Selection**
   - On Enter key in dropdown, query `document.activeElement` or the element with `.keyboard-focus` class
   - Use the actually focused element instead of relying on `state.dropdownFocusIndex`
   - This works regardless of whether arrow navigation updated internal state

2. **Alternative: Sync State with Bootstrap Focus** (if approach 1 insufficient)
   - Listen to focus events on dropdown items
   - Update `state.dropdownFocusIndex` when focus changes
   - Ensures arrow navigation (handled by Bootstrap) updates our state

3. **Preserve Existing Functionality**
   - Number keys 1-6 must continue to work for rejection categories
   - Escape must continue to close dropdown
   - Visual `.keyboard-focus` class styling must be preserved

### Error Handling

- **No focused element found**: Fall back to `state.dropdownFocusIndex` (current behavior)
- **Dropdown already closed**: No-op (don't throw errors)

## Test Requirements

### Coverage Target: **Manual testing** (client-side JavaScript)

### Test Scenarios (6+ manual tests)

1. **Arrow + Enter in Reject dropdown**
   - Press `R`, ArrowDown twice, Enter - should select 3rd item ("Wrong Value Extracted")
   - Verify rejection panel shows correct category

2. **Arrow + Enter in Reclassify dropdown**
   - Press `C`, ArrowDown, Enter - should select 2nd metric
   - Verify decision is submitted with correct metric ID

3. **Wrap-around navigation**
   - Press `R`, ArrowUp (at first item) - should wrap to last item ("Other")
   - Press Enter - should select "Other"

4. **Number keys still work**
   - Press `R`, press `3` - should still select "Wrong Value Extracted"

5. **Mixed navigation**
   - Press `R`, ArrowDown, ArrowDown, press `1` - number key should override arrow position

6. **Escape still works**
   - Press `R`, ArrowDown, Escape - should close without selection

## Acceptance Criteria

- [ ] ArrowDown/ArrowUp + Enter selects the visually focused dropdown item
- [ ] Console log shows correct index on Enter (not -1)
- [ ] Number keys 1-6 continue to work for rejection categories
- [ ] Escape continues to close dropdown without selection
- [ ] Keyboard hints panel continues to update dynamically
- [ ] All existing keyboard shortcuts still work (A, F, R, C, N, P)
- [ ] No JavaScript console errors

## Do NOT

- Modify any Python backend code
- Change dropdown HTML structure in `review.html`
- Remove or modify the existing number key (1-6) functionality
- Add external dependencies
- Change the CSS styling for `.keyboard-focus`

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug --port 5001

# Manual testing in browser:
# 1. Navigate to http://127.0.0.1:5001/filings
# 2. Click "Start Review" on any filing with pending candidates
# 3. Run test scenarios above
# 4. Open browser console (F12) to verify log messages

# Optional: Use Playwright for automated testing
# (See test scenarios above)
```

## Critical Evaluation Phase

**Required for all tasks. Depth: Standard (S task)**

After verification passes but BEFORE committing:
1. Code Quality Review - Check for linting issues, verify no regressions
2. Test Coverage Assessment - Verify all 6 test scenarios pass
3. Architecture Alignment - Ensure fix follows existing JS patterns
4. Identify Improvements - Note any related edge cases
5. **User Approval (REQUIRED)** - STOP and ask before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for deferred improvements
8. Commit and Push

## Expected Impact

**Before UXI-1a**:
- Arrow + Enter: Selects wrong item or nothing
- User must use number keys or mouse as workaround

**After UXI-1a**:
- Arrow + Enter: Selects the visually focused item correctly
- Full keyboard-only workflow possible for all dropdown interactions

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example approach</summary>

```javascript
// Approach 1: Query focused element on Enter
function selectFocusedDropdownItem() {
    if (!state.activeDropdown) return;

    // Get currently focused element (Bootstrap manages this)
    const focusedItem = document.activeElement;

    // Verify it's a dropdown item
    if (focusedItem &&
        (focusedItem.classList.contains('rejection-category-option') ||
         focusedItem.classList.contains('metric-option'))) {
        focusedItem.click();
        return;
    }

    // Fallback to index-based selection (existing behavior)
    const items = getActiveDropdownItems();
    if (state.dropdownFocusIndex >= 0 && state.dropdownFocusIndex < items.length) {
        items[state.dropdownFocusIndex].click();
    }
}

// Approach 2: Sync state with focus events
function initializeDropdownKeyboardNavigation() {
    // ... existing code ...

    // Add focus listener to sync state
    document.querySelectorAll('.rejection-category-option, .metric-option')
        .forEach((item, index) => {
            item.addEventListener('focus', () => {
                state.dropdownFocusIndex = index;
            });
        });
}
```
</details>

## Reference

- **Issue source**: UXI-1 Playwright testing (2026-01-07)
- **Related**: UXI-1 (parent task), HRI-5 (original keyboard shortcuts)
- **Root cause**: Bootstrap dropdown intercepts ArrowDown/ArrowUp events

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6

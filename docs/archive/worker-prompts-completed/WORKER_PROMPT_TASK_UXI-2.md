# WORKER PROMPT: Task UXI-2 - Metric Dropdown Search

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2
TASK NAME:     Add search/filter input to metric reclassify dropdown
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3h (breakdown: HTML 30 min, JS filtering 60 min, styling 30 min, testing 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (requires integration with UXI-1 keyboard navigation)
TASK SIZE:     M
DEPENDS ON:    UXI-1 (dropdown keyboard navigation must be implemented first)
UNLOCKS:       UXI-4
BLOCKS:        None
PARALLEL WITH: UXI-3
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add a search input to the metric reclassify dropdown that filters the list as the user types.

**Business Rationale**: With ~36 metrics in a 300px scrollable dropdown, finding a specific metric takes 5-10 seconds. Expert reviewers who know metric names (e.g., "ARR", "retention") need faster access.

**Current Behavior**: Reclassify dropdown shows all metrics in scrollable list. No search capability. User must visually scan or scroll.

**Desired Behavior**: Search input at top of dropdown (sticky). Typing immediately filters visible metrics. Matches against metric_id and display_name. Auto-focus on dropdown open.

## Prerequisites

- **UXI-1 must be complete**: This task modifies UXI-1's dropdown keyboard navigation code

## Files to Modify

1. **`src/web/templates/review.html`** - Add search input to reclassify dropdown
2. **`src/web/static/js/review.js`** - Add filtering logic + modify UXI-1 integration points
3. **`src/web/static/css/review.css`** - Add styles for search container and no-matches state

## Files to Read (Context Only)

- `src/web/templates/review.html` lines 616-640 - Existing dropdown structure
- `src/web/static/js/review.js` lines 483-520 - Dropdown event handlers (UXI-1)
- `src/web/static/js/review.js` lines 596-606 - `getActiveDropdownItems()` function (UXI-1)
- `src/web/static/js/review.js` lines 637-656 - `navigateDropdown()` function (UXI-1)
- `src/web/static/js/review.js` lines 665-689 - `selectFocusedDropdownItem()` function (UXI-1)
- `src/web/static/js/review.js` lines 1118-1128 - `isInputField` check for keyboard shortcuts

## Implementation Requirements

### Critical UXI-1 Integration Points

**IMPORTANT**: The existing UXI-1 keyboard navigation must be updated to work with filtered results.

1. **Update `getActiveDropdownItems()` function** (review.js ~line 600)
   - Current: `document.querySelectorAll('.metric-option')`
   - Change to: `document.querySelectorAll('.metric-option:not(.d-none)')`
   - This ensures arrow keys only navigate visible (filtered) items

2. **Modify dropdown open handler for reclassify** (review.js ~line 509)
   - Current: Sets `state.dropdownFocusIndex = 0` (focuses first item)
   - Change to: Set `state.dropdownFocusIndex = -1` (no item focused initially)
   - Then focus the search input element instead
   - **Note**: Only modify reclassify dropdown, NOT rejection dropdown

3. **Clear search on dropdown close** (review.js ~line 517)
   - Add: Clear search input value and reset filter when dropdown closes
   - Call the filter function with empty string to show all items
   - Ensures fresh state on next open

4. **Add arrow key exception for search input** (review.js ~line 1134-1144) ⚠️ **NEW**
   - **Problem**: Current code intercepts ArrowUp/ArrowDown when `state.activeDropdown` is set
   - This prevents cursor movement in the search input
   - **Fix**: Before calling `navigateDropdown()`, check if `document.activeElement` is the search input
   - If in search input: ArrowDown should set `dropdownFocusIndex = 0` and move focus to first visible item
   - If in search input: ArrowUp should do nothing (or optionally close dropdown)

5. **Update `selectFocusedDropdownItem()` for single-match Enter** (review.js ~line 665) ⚠️ **NEW**
   - **Problem**: When search input is focused, `document.activeElement` is the input, not a `.metric-option`
   - Current code checks if `activeElement` has `.metric-option` class - this fails when input is focused
   - **Fix**: Add new logic at the START of the function:
     ```javascript
     // UXI-2: Auto-select single visible match when Enter pressed in search
     if (state.activeDropdown === 'reclassify' && state.dropdownFocusIndex === -1) {
         const visibleItems = document.querySelectorAll('.metric-option:not(.d-none)');
         if (visibleItems.length === 1) {
             visibleItems[0].click();
             console.log('Auto-selected single visible match');
             return;
         }
     }
     ```

### HTML Structure Change

**⚠️ CRITICAL**: The original structure had an invalid `<div>` as direct child of `<ul>`. Use this valid HTML structure instead:

```html
<ul class="dropdown-menu metric-selector">
    <li class="metric-search-container">
        <div class="input-group input-group-sm">
            <input type="text"
                   id="metric-search-input"
                   class="form-control metric-search-input"
                   placeholder="Search metrics..."
                   autocomplete="off"
                   aria-label="Search metrics">
            <button class="btn btn-outline-secondary metric-search-clear"
                    type="button"
                    aria-label="Clear search"
                    style="display: none;">×</button>
        </div>
    </li>
    <li><h6 class="dropdown-header">Choose Correct Metric</h6></li>
    <li class="metric-list-wrapper">
        <ul class="metric-list list-unstyled mb-0">
            {% for metric in metrics %}
                <li>
                    <a class="dropdown-item metric-option"
                       href="#"
                       data-metric-id="{{ metric.metric_id }}"
                       role="option">
                        <div class="small text-primary">{{ metric.metric_id }}</div>
                        <div>{{ metric.display_name }}</div>
                    </a>
                </li>
            {% endfor %}
        </ul>
    </li>
    <li class="no-matches-message" style="display: none;" aria-live="polite">
        No matching metrics
    </li>
</ul>
```

**Key structural changes from original:**
- Nested `<ul class="metric-list">` inside `<li class="metric-list-wrapper">` for valid HTML
- Added `id="metric-search-input"` for easy JS targeting
- Added `aria-label` attributes for accessibility
- Added `aria-live="polite"` on no-matches message for screen readers
- Added `role="option"` on metric items

### CSS Additions (review.css)

Add these styles to support the new structure:

```css
/* =============================================================================
   Metric Search (UXI-2)
   ============================================================================= */
.metric-selector {
    max-height: 300px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.metric-search-container {
    flex-shrink: 0;
    padding: 0.5rem;
    background: white;
    border-bottom: 1px solid var(--color-border);
}

.metric-list-wrapper {
    flex: 1;
    overflow-y: auto;
    min-height: 0; /* Required for flex overflow */
}

.metric-list-wrapper .metric-list {
    margin: 0;
    padding: 0;
}

.no-matches-message {
    flex-shrink: 0;
    text-align: center;
    color: var(--color-muted);
    padding: 0.75rem;
}

.metric-search-clear {
    border-left: 0;
}
```

### Core Functionality

1. **Search Input Element**
   - Add `<input>` at top of reclassify dropdown menu
   - Sticky via flexbox structure (search container has `flex-shrink: 0`)
   - Placeholder: "Search metrics..."
   - Small size (`input-group-sm`), include clear button (×)

2. **Real-Time Filtering**
   - Filter on `input` event (handles typing and paste)
   - Match against metric_id AND display_name (case-insensitive)
   - Hide non-matching options (`d-none` class on the `<li>` containing the `.metric-option`)
   - Empty search shows all metrics
   - Show/hide "No matching metrics" message based on results

3. **Auto-Focus Behavior**
   - Focus search input when reclassify dropdown opens (via `C` key or click)
   - Immediate typing without extra clicks
   - `Escape` closes dropdown (handled by existing code), search cleared on close

4. **Keyboard Integration** ⚠️ **UPDATED**
   - Typing in search does NOT trigger other shortcuts (A/R/C/N/P) - already handled by existing `isInputField` check at line 1121-1127
   - Arrow keys navigate visible (filtered) items only - requires `getActiveDropdownItems()` fix
   - **ArrowDown in search input**: Sets `dropdownFocusIndex = 0`, moves focus to first visible item
   - **ArrowUp in search input**: No action (cursor stays in input)
   - **Enter when `dropdownFocusIndex === -1`**: If exactly one visible item, auto-select it
   - **Enter when item is focused**: Select that item (existing behavior)

5. **Clear Button Behavior**
   - Show clear button (×) only when search has text
   - Click clears search and resets filter
   - Re-focus search input after clear

6. **No Matches State**
   - Show "No matching metrics" when filter yields nothing
   - Styled consistently (muted, centered)
   - Hide when search cleared or matches found
   - `aria-live="polite"` announces to screen readers

### JavaScript Implementation Outline

```javascript
// Add to initializeDropdownKeyboardNavigation() or create new function

function initializeMetricSearch() {
    const searchInput = document.getElementById('metric-search-input');
    const clearBtn = document.querySelector('.metric-search-clear');
    const noMatchesMsg = document.querySelector('.no-matches-message');

    if (!searchInput) return;

    // Filter on input
    searchInput.addEventListener('input', (e) => {
        filterMetrics(e.target.value);
    });

    // Clear button
    clearBtn?.addEventListener('click', () => {
        searchInput.value = '';
        filterMetrics('');
        searchInput.focus();
    });

    // Prevent dropdown close when clicking in search
    searchInput.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

function filterMetrics(query) {
    const searchInput = document.getElementById('metric-search-input');
    const clearBtn = document.querySelector('.metric-search-clear');
    const noMatchesMsg = document.querySelector('.no-matches-message');
    const metricItems = document.querySelectorAll('.metric-list > li');

    const normalizedQuery = query.toLowerCase().trim();
    let visibleCount = 0;

    metricItems.forEach(li => {
        const option = li.querySelector('.metric-option');
        if (!option) return;

        const metricId = option.dataset.metricId?.toLowerCase() || '';
        const displayName = option.textContent?.toLowerCase() || '';

        const matches = normalizedQuery === '' ||
                       metricId.includes(normalizedQuery) ||
                       displayName.includes(normalizedQuery);

        li.classList.toggle('d-none', !matches);
        if (matches) visibleCount++;
    });

    // Show/hide clear button
    if (clearBtn) {
        clearBtn.style.display = query.length > 0 ? 'block' : 'none';
    }

    // Show/hide no matches message
    if (noMatchesMsg) {
        noMatchesMsg.style.display = visibleCount === 0 ? 'block' : 'none';
    }

    // Reset focus index when filtering
    state.dropdownFocusIndex = -1;
    removeDropdownFocus();
}

function clearMetricSearch() {
    const searchInput = document.getElementById('metric-search-input');
    if (searchInput) {
        searchInput.value = '';
        filterMetrics('');
    }
}
```

### Error Handling

- **Empty dropdown**: Show "No metrics available" (rare edge case)
- **Special characters**: Use `includes()` not regex to avoid escaping issues
- **Null checks**: Guard against missing elements (searchInput, clearBtn, etc.)

## Test Requirements

### Coverage Target: **Manual testing** (client-side JavaScript)

### Test Scenarios (14 manual tests) ⚠️ **UPDATED: Added 2 new tests**

**Basic Filtering:**
1. Press `C`, type "arr" - show only ARR metric
2. Clear search (click ×) - show all metrics
3. Type "revenue" - show metrics with "revenue" in name
4. "ARR" and "arr" give same results (case insensitive)
5. "Daily Active" matches "cm_daily_active_users"
6. Type "xyz123" - show "No matching metrics" message
7. Paste text into search - filters correctly
8. Focus auto-moves to search on dropdown open

**Arrow Key Integration (UXI-1 compatibility):**
9. Type "cust", then press Arrow Down - highlights first visible match AND moves focus out of input
10. Type "cust", press Arrow Down twice - skips hidden items, moves through visible only
11. Type to filter to 1 result, press Enter without Arrow - selects that single match
12. Close dropdown (Escape), reopen - search is cleared, all metrics visible

**New Keyboard Edge Cases:** ⚠️ **NEW**
13. In search input, press Arrow Up - cursor stays in input, no navigation
14. Type in search input, use left/right arrows - cursor moves in input (not intercepted)

**UXI-1 Regression:**
15. Rejection dropdown (R key) - arrow keys still work, no search input present

## Acceptance Criteria

- [ ] Search input appears at top of reclassify dropdown
- [ ] Input is sticky (visible while scrolling list)
- [ ] Typing filters metrics in real-time
- [ ] Matches against both metric_id and display_name
- [ ] Case-insensitive matching
- [ ] "No matching metrics" shown when filter yields nothing
- [ ] Auto-focus on search input when dropdown opens
- [ ] Arrow key navigation works on filtered results only (no hidden items)
- [ ] ArrowDown from search input moves focus to first visible item
- [ ] ArrowUp in search input does NOT navigate (allows cursor movement)
- [ ] Clear button (×) resets filter and shows only when search has text
- [ ] Typing does NOT trigger A/R/C/N/P shortcuts
- [ ] Enter on single visible match auto-selects it
- [ ] Search clears when dropdown closes
- [ ] Works in Chrome, Firefox, Safari
- [ ] HTML structure is valid (no `<div>` as direct child of `<ul>`)
- [ ] Accessibility: `aria-label` on input, `aria-live` on no-matches message

## Do NOT

- Modify Python backend code
- Change metric ordering logic in `review.py`
- Add external search libraries
- Modify rejection dropdown (only reclassify)
- Change metric data structure
- Break existing UXI-1 keyboard navigation for rejection dropdown
- Use `<div>` as direct child of `<ul>` (invalid HTML)

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug

# Manual testing in browser - see Test Scenarios above
# Test both Chrome and Firefox minimum

# Validate HTML structure (optional)
# Use browser DevTools to inspect dropdown structure
# Ensure no console warnings about invalid HTML
```

## Critical Evaluation Phase

**Required for all tasks. Depth: Standard (M task)**

After verification passes but BEFORE committing:
1. Code Quality Review - Check for linting issues, DRY violations
2. Test Coverage Assessment - Verify all 15 scenarios tested manually (including regression)
3. Architecture Alignment - Ensure follows existing patterns in review.js
4. UXI-1 Regression Check - Verify rejection dropdown still works with arrow keys
5. HTML Validation - Confirm no invalid nesting (DevTools console)
6. Accessibility Check - Verify aria attributes work with screen reader (optional)
7. Identify Improvements - Note optimizations or edge cases
8. **User Approval (REQUIRED)** - STOP and ask before proceeding
9. Implement Approved Changes
10. Generate Follow-Up Tasks for deferred improvements
11. Commit and Push

## Reference

- **Issue source**: UI/UX Review (2026-01-06)
- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`
- **Related**: UXI-1 (Dropdown Keyboard Navigation), UXI-4 (Recent Metrics)
- **Critical evaluation**: 2026-01-07 - Fixed HTML structure, added arrow key handling for search input

## Change Log

| Date | Change | Reason |
|------|--------|--------|
| 2026-01-07 | Initial version | Created from UX_IMPROVEMENT_PLAN.md |
| 2026-01-07 | Fixed HTML structure | Invalid `<div>` inside `<ul>` - now uses nested `<ul>` |
| 2026-01-07 | Added arrow key exception | ArrowDown/Up intercepted even when in search input |
| 2026-01-07 | Added single-match Enter logic | `selectFocusedDropdownItem()` fails when input focused |
| 2026-01-07 | Added accessibility attributes | Missing aria-label, aria-live |
| 2026-01-07 | Added CSS file to modify list | Flexbox layout needed for new structure |
| 2026-01-07 | Expanded test scenarios | Added keyboard edge cases (13-14) and regression test (15) |

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6

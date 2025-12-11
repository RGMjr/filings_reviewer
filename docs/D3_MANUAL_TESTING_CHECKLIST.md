# D3 Manual Testing Checklist

**Date:** 2025-12-10
**Component:** Filing List Template (D3)
**Server:** http://127.0.0.1:5000

## Test Data Summary

The following test data has been generated:
- **5 companies** (CloudTech, DataFlow, NetworkHub, FinTech, E-Commerce)
- **10 filings** (2 per company, S-1 forms)
- **45 source segments** (customer metrics like ARR, NRR, CAC, etc.)
- **45 review candidates**
  - 40 pending (for testing pending filter)
  - 5 reviewed (for testing reviewed filter and overall progress)

## Manual Test Cases

### ✅ Test Case 1: All Filings (No Filter)

**URL:** http://127.0.0.1:5000/filings

**Steps:**
1. Open the URL in your browser
2. Verify page loads successfully

**Expected Results:**
- [X] Page title shows "Filings Review"
- [X] Overall Progress section displays:
  - [X] "X/45 reviewed (Y%)" text
  - [X] Multi-segment progress bar with:
    - [ ] Green segment for reviewed candidates
    - [X] Yellow segment for pending candidates
  - [ ] "X of 10 filings have pending candidates" text
- [X] Filter dropdown shows "All Filings" selected
- [X] Filing cards grid displays:
  - [X] 10 filing cards visible (or first page if paginated)
  - [ ] Each card shows:
    - [X] Company name (e.g., "CloudTech Solutions, Inc.")
    - [X] CIK number
    - [X] Form type (S-1)
    - [X] Filing date
    - [X] Accession number
    - [X] Status badge (Pending or Reviewed)
    - [X] Review progress bar
    - [S] Statistics (total, pending, reviewed counts)
    - [X] "Start Review" or "View Reviewed Candidates" button

**Screenshots:**
- [X] Take screenshot of overall progress section
- [X] Take screenshot of filing cards grid

---

### ✅ Test Case 2: Pending Filter

**URL:** http://127.0.0.1:5000/filings?status=pending

**Steps:**
1. Navigate to the filing list page
2. Select "Pending" from the status filter dropdown
3. Click "Apply Filter"

**Expected Results:**
- [X] URL updates to include `?status=pending`
- [X] Filter dropdown shows "Pending" selected
- [X] "Clear Filter" button appears
- [X] Only filings with pending candidates are shown
  - [X] All visible cards should have "Pending" status badge (yellow)
  - [X] All cards should show `pending_count > 0`
- [X] "Start Review" button text includes pending count
  - [X] Example: "Start Review (4 pending)"

**Screenshots:**
- [X] Take screenshot showing pending filter active

---

### ✅ Test Case 3: Reviewed Filter

**URL:** http://127.0.0.1:5000/filings?status=reviewed

**Steps:**
1. Navigate to the filing list page
2. Select "Reviewed" from the status filter dropdown
3. Click "Apply Filter"

**Expected Results:**
- [X] URL updates to include `?status=reviewed`
- [X] Filter dropdown shows "Reviewed" selected
- [X] "Clear Filter" button appears
- [ ] Only filings with NO pending candidates are shown
  - [ ] All visible cards should have "Reviewed" status badge (green)
  - [ ] All cards should show `pending_count = 0`
- [ ] Button text changes to "View Reviewed Candidates"

**Screenshots:**
- [ ] Take screenshot showing reviewed filter active

---

### ✅ Test Case 4: Clear Filter

**Steps:**
1. Apply any filter (pending or reviewed)
2. Click the "Clear Filter" button

**Expected Results:**
- [X] URL updates to `/filings` (no status param)
- [X] Filter dropdown resets to "All Filings"
- [X] "Clear Filter" button disappears
- [X] All filings are shown again

---

### ✅ Test Case 5: Pagination (if applicable)

**Note:** With 10 filings and default `per_page=50`, pagination may not be visible. To test pagination, you would need more filings or reduce `per_page` in the URL.

**URL:** http://127.0.0.1:5000/filings?per_page=5

**Steps:**
1. Navigate to URL with `per_page=5` to force pagination
2. Verify pagination controls appear

**Expected Results:**
- [ ] Pagination controls visible at bottom
- [ ] "Previous" button disabled on page 1
- [ ] "Next" button enabled
- [ ] Page numbers shown (1, 2, 3...)
- [ ] Page info text shows correct range
  - [ ] Example: "Page 1 of 2 • Showing 1-5 of 10 filings"
- [ ] Click "Next" button:
  - [ ] URL updates to `?page=2`
  - [ ] Next 5 filings load
  - [ ] "Previous" button becomes enabled
  - [ ] "Next" button disabled on last page

---

### ✅ Test Case 6: Filing Card Click

**Steps:**
1. Click "Start Review" button on any filing card with pending candidates

**Expected Results:**
- [X] Browser navigates to `/review/{filing_id}`
- [X] Review interface loads (D4 - not yet implemented)
  - [X] You'll see a 404 or error since D4 isn't complete yet
  - [X] This is expected - just verify the URL is correct

---

### ✅ Test Case 7: Responsive Layout

**Desktop (≥ 1200px width):**
- [X] Filing cards displayed in 3 columns
- [X] Cards aligned in grid
- [X] All cards have equal height

**Tablet (768-1199px width):**
- [ ] Filing cards displayed in 2 columns
- [ ] Cards aligned in grid

**Mobile (< 768px width):**
- [ ] Filing cards displayed in 1 column (stacked)
- [ ] Cards full width
- [ ] All content readable

**Steps:**
1. Resize browser window or use browser dev tools responsive mode
2. Test at widths: 320px, 768px, 992px, 1200px

---

### ✅ Test Case 8: Empty State

**Note:** To test empty state, you would need to clear all candidates from database.

**Alternative:** Test by filtering for a status that has no results (if you mark all as reviewed, pending filter will show empty state)

**Expected Results:**
- [X] Empty state alert box displayed
- [X] Message: "No filings found with review candidates"
- [X] Helpful instructions shown with command to run

---

## Visual/UI Checks

### Overall Appearance:
- [X] Bootstrap 5 styling applied correctly
- [X] Colors and fonts consistent with base template
- [X] No layout shifts or broken elements
- [X] Progress bars display correctly
- [X] Badges (Pending/Reviewed) have correct colors

### Accessibility:
- [ ] All progress bars have ARIA attributes
- [ ] Form controls have labels
- [ ] Pagination has aria-label
- [ ] Color contrast sufficient for text

### Performance:
- [X] Page loads quickly (< 2 seconds)
- [X] No JavaScript errors in console
- [X] No broken image links
- [X] All links functional

---

## Browser Testing

Test in multiple browsers:
- [X] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari (if on macOS)

---

## Issues Found

**Document any issues discovered during testing:**

| Test Case | Issue Description | Severity | Status |
|-----------|------------------|----------|--------|
| Example: TC1 | Progress bar width incorrect | Low | Open |
|  |  |  |  |
|  |  |  |  |
|  |  |  |  |

---

## Test Summary

**Tester:** _________________
**Date:** _________________
**Duration:** _________________

**Results:**
- Total Test Cases: 8
- Passed: ___
- Failed: ___
- Blocked: ___

**Overall Status:** ☐ Pass ☐ Fail ☐ Needs Work

**Notes:**
_____________________________________________
_____________________________________________
_____________________________________________

---

## Next Steps After Testing

Once D3 testing is complete:

1. **Document any bugs/issues** found and fix them
2. **Take screenshots** of the working UI for documentation
3. **Move to D4:** Create `src/web/templates/review.html` (main review interface)
4. **Create B3:** Generate review candidates script (for production data)
5. **Create D6:** Production-ready server startup script

---

## Quick Command Reference

```bash
# Start development server
python3 scripts/run_dev_server.py

# View in browser
open http://127.0.0.1:5000/filings

# Check database for test data
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
  -c "SELECT COUNT(*) FROM review_candidates WHERE review_status = 'pending';"

# Regenerate test data (if needed)
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis \
  -f scripts/generate_test_data_sql.sql

# Stop server
# Press Ctrl+C in the terminal where server is running
# OR find the process: ps aux | grep run_dev_server
# Kill it: kill -9 <PID>
```

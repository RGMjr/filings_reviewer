# WORKER PROMPT: Task UXI-9 - "Other" Rejection Category UX

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-9
TASK NAME:     Improve "Other" rejection category UX
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: <30 min
TIME ACTUAL:   N/A
RISK LEVEL:    None (minor UX enhancement)
TASK SIZE:     XS
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-8
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Improve UX when "Other" rejection category is selected by auto-focusing reason textarea and showing helper text.

**Business Rationale**: Selecting "Other" requires additional text input, but this isn't obvious. Users may submit without explanation.

**Current Behavior**: Selecting "Other" shows rejection panel but doesn't guide user to provide reason.

**Desired Behavior**: Selecting "Other" auto-focuses reason textarea and shows helper: "Please describe the reason for rejection."

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/web/static/js/review.js`** - Add special handling for "Other" selection

## Implementation Requirements

### Core Functionality

1. **Auto-Focus Textarea**
   - When "Other" selected, focus moves to rejection reason textarea
   - Cursor ready for immediate typing

2. **Helper Text**
   - Show helper below textarea: "Please describe why this candidate is being rejected."
   - Only visible when "Other" is selected
   - Remove/hide when different category selected

### Error Handling

- **Textarea not found**: Log warning, no crash

## Acceptance Criteria

- [ ] Selecting "Other" auto-focuses reason textarea
- [ ] Helper text appears for "Other" category
- [ ] Helper text hidden for other categories
- [ ] Focus and helper work after switching categories

## Do NOT

- Make reason required for "Other" (keep optional)
- Change rejection panel layout
- Modify other category behavior

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug
```

### Playwright E2E Tests (via MCP)

Use the Playwright MCP server for browser automation testing:

```
# Test 1: Selecting "Other" auto-focuses textarea
1. browser_navigate to /review/filings/<filing_id>/candidates/<candidate_id>
2. browser_click on Reject dropdown button
3. browser_click on "Other" option
4. browser_snapshot to verify:
   - Rejection reason textarea has focus
   - Helper text "Please describe why..." is visible

# Test 2: Helper text hidden for non-Other categories
1. browser_navigate to a candidate page
2. browser_click on Reject dropdown
3. browser_click on "Wrong Metric Type"
4. browser_snapshot to verify helper text is NOT visible
5. browser_click on Reject dropdown again
6. browser_click on "Other"
7. browser_snapshot to verify helper text IS visible
8. browser_click on Reject dropdown again
9. browser_click on "Duplicate"
10. browser_snapshot to verify helper text is hidden again

# Test 3: Focus + helper work after category switching
1. browser_navigate to a candidate page
2. browser_click on Reject dropdown
3. browser_click on "Wrong Value"
4. browser_click on Reject dropdown
5. browser_click on "Other"
6. browser_snapshot to verify textarea has focus and helper visible
```

## Critical Evaluation Phase

**Depth: Quick scan (XS task)** - Check for obvious issues only.

## Reference

- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

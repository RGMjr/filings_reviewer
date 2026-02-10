# WORKER PROMPT: Task UXI-8 - Focus Management After Navigation

> **⛔ DROPPED** (2026-01-07)
>
> **Reason**: Critical evaluation revealed this task addresses a non-existent problem.
> - Existing keyboard shortcuts (`A`, `R`, `C`) already provide immediate keyboard access
> - Auto-focus on Accept would bias the review process toward acceptance
> - Could harm accessibility (WCAG 2.4.3 Focus Order, 3.2.1 On Focus)
> - Risk of accidental submissions if Enter pressed during page load
> - Contradicts natural "read first, then act" UX pattern

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-8
TASK NAME:     Auto-focus Accept button after candidate navigation
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        ⛔ DROPPED
COMPLETION:    N/A (task dropped)
TIME ESTIMATE: 1h (breakdown: JS 30 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (accessibility improvement)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Auto-focus the Accept button after navigating to a new candidate for seamless keyboard flow.

**Business Rationale**: After pressing N/P or submitting a decision, keyboard users must tab to reach action buttons. Auto-focus enables immediate Enter to accept.

**Current Behavior**: Focus not explicitly managed after navigation. User must tab or click.

**Desired Behavior**: After page load for new candidate, focus moves to Accept button. Visual focus indicator visible.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/web/static/js/review.js`** - Add focus management on page init

## Implementation Requirements

### Core Functionality

1. **Focus on Page Load**
   - After `DOMContentLoaded` and init complete, focus Accept button
   - Use `element.focus()` with visible focus ring

2. **Focus After Decision**
   - If staying on same page (error case), refocus Accept
   - Redirect handles focus on new page

### Error Handling

- **Accept button not present** (already reviewed): Focus next available action

## Acceptance Criteria

- [ ] Accept button focused on page load
- [ ] Visual focus indicator visible
- [ ] Pressing Enter immediately after load accepts candidate
- [ ] Focus not disrupted by other init operations

## Do NOT

- Add focus to other elements unexpectedly
- Remove existing focus behavior in dropdowns
- Change tab order

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug

# Navigate to candidate, verify Accept is focused
# Press Enter immediately - should accept
```

## Critical Evaluation Phase

**Depth: Standard (S task)** - After verification, identify improvements, get user approval.

## Reference

- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

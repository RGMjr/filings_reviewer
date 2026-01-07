# WORKER PROMPT: Task UXI-4 - Recent Metrics Section

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-4
TASK NAME:     Add recent metrics section to reclassify dropdown
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2h (breakdown: JS storage 30 min, UI 45 min, testing 45 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (client-side only, no backend changes)
TASK SIZE:     S
DEPENDS ON:    UXI-2 (search input provides dropdown structure)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-5, UXI-6
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Show "Recently Used" section at top of metric reclassify dropdown, tracking selections in sessionStorage.

**Business Rationale**: Reviewers often work on similar filings and repeatedly select the same metrics (e.g., ARR, NRR). Showing recent selections reduces scroll/search time.

**Current Behavior**: All metrics shown in fixed order. No tracking of recent selections.

**Desired Behavior**: Top section shows last 5 metrics used this session. Clicking a recent metric works same as regular selection. Section appears below search input (from UXI-2).

## Prerequisites

- **UXI-2** (Metric Dropdown Search) - Provides dropdown structure with search input

## Files to Modify

1. **`src/web/templates/review.html`** - Add recent metrics section structure
2. **`src/web/static/js/review.js`** - Add sessionStorage tracking and rendering

## Implementation Requirements

### Core Functionality

1. **Session Storage Tracking**
   - Store last 5 selected metrics in `sessionStorage`
   - Key: `recentMetrics` (JSON array of metric_ids)
   - Update on each reclassify selection
   - FIFO: oldest drops off when exceeding 5

2. **UI Section**
   - Header: "Recently Used" (small, muted)
   - Show below search input, above main list
   - Same styling as regular metric items
   - Divider line below recent section

3. **Behavior**
   - Clicking recent metric triggers same selection flow
   - Recent section updates immediately on selection
   - Empty state: hide section if no recent metrics

### Error Handling

- **sessionStorage unavailable**: Gracefully degrade, hide section
- **Invalid stored data**: Clear and start fresh

## Test Requirements

### Coverage Target: **Manual testing** (client-side JavaScript)

### Test Scenarios (5+ tests)

1. Select metric → appears in Recent section
2. Select 6 metrics → oldest dropped, newest shown
3. Recent metric click → works same as regular click
4. New session → starts with empty recents
5. Same metric twice → moves to top, no duplicates

## Acceptance Criteria

- [ ] Recent metrics section appears below search input
- [ ] Last 5 unique metrics tracked in sessionStorage
- [ ] Clicking recent metric triggers selection
- [ ] Recent section hidden when empty
- [ ] No duplicates in recent list
- [ ] Section updates immediately on selection

## Do NOT

- Add backend persistence (session-only)
- Modify metric ordering logic
- Track across browser sessions (use sessionStorage, not localStorage)

## Verification Commands

```bash
# Start dev server
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug

# Manual testing in browser
```

## Critical Evaluation Phase

**Depth: Standard (S task)** - After verification, identify improvements, get user approval.

## Reference

- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`
- **Related**: UXI-2 (Search input structure)

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

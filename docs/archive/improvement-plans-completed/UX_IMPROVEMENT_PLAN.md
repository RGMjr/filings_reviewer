# Human Review UI/UX Improvement Plan

**Created**: 2026-01-06
**Status**: ✅ COMPLETE
**Goal**: Improve reviewer productivity and interface usability

---

## Executive Summary

This plan addresses UI/UX improvements identified in a comprehensive review of the human review system. The focus areas are:

1. **Keyboard shortcuts** - Enabling faster navigation without mouse
2. **Dropdown usability** - Making metric selection faster with search and recents
3. **General UX polish** - Confidence tooltips, focus management, etc.

### Task Summary

| Priority | Tasks | Effort | Status |
|----------|-------|--------|--------|
| High | UXI-1, UXI-2, UXI-3, UXI-5 | 6-9 hours | Complete |
| Medium | UXI-6 | 30 min | Complete |
| **Total** | **6 tasks** | **7-10 hours** | ✅ Complete |

**Dropped Tasks**:
- UXI-4 (Recent Metrics) - Redundant with UXI-2 search functionality; sessionStorage choice contradicted business rationale
- UXI-7 (Metric Abbreviations) - Low value, adds maintenance burden for abbreviation list
- UXI-8 (Focus Management) - Existing keyboard shortcuts already solve the stated problem; auto-focus on Accept would bias reviews and harm accessibility
- UXI-9 ("Other" Rejection UX) - Auto-focus already implemented for ALL categories (`review.js:846-849`); proposed helper text duplicates existing placeholder ("Why is this not the correct metric?")

---

## Phase 1: Keyboard Navigation (High Priority)

### UXI-1: Dropdown Keyboard Navigation

**Problem**: After pressing `R` or `C`, user must use mouse to select from dropdown.

**Solution**: Add number keys (1-6) for rejection categories and arrow key navigation for both dropdowns.

| Aspect | Details |
|--------|---------|
| Size | M (2-3 hours) |
| Risk | Low |
| Files | `src/web/static/js/review.js` |
| Dependencies | None |

**Alternatives Considered**:
- **A. Number keys only**: Fast but not accessible
- **B. Arrow keys only**: Accessible but slower
- **C. First-letter navigation**: Ambiguous with similar names
- **D. Combined (selected)**: Best of both worlds

---

### UXI-2: Metric Dropdown Search

**Problem**: With ~20 metrics, scrolling through a 300px dropdown is slow.

**Solution**: Add search input at top of reclassify dropdown. Typing filters visible options in real-time.

| Aspect | Details |
|--------|---------|
| Size | M (2-3 hours) |
| Risk | Low |
| Files | `src/web/templates/review.html`, `src/web/static/js/review.js` |
| Dependencies | None |

**Alternatives Considered**:
- **A. Static search input (selected)**: Discoverable, familiar pattern
- **B. Type-ahead without input**: Not discoverable for new users
- **C. Grouped headers with collapse**: More clicks required
- **D. Full combobox replacement**: Too invasive

---

### UXI-3: Skip/Defer Shortcut

**Problem**: No way to skip a candidate without making a decision.

**Solution**: Add `S` key shortcut to set status to "skipped" and navigate to next.

| Aspect | Details |
|--------|---------|
| Size | S (1-2 hours) |
| Risk | Low |
| Files | `src/web/static/js/review.js`, `src/web/routes/api.py` |
| Dependencies | None |

**Existing Infrastructure** (verified 2026-01-06):
- `db.update_candidate_status(id, 'skipped')` - exists in `db.py:994`
- `REVIEW_STATUSES` includes "skipped" - defined in `models.py:115`
- Filter dropdown "Skipped" option - exists in `review.html:128`
- Progress bar tracks `skipped_count` - exists in filing list

**Implementation Scope**: Wire existing DB method to new API endpoint + add keyboard handler.

**Alternatives Considered**:
- **A. Skip without status**: Loses track of skipped items
- **B. Skip with status (selected)**: Trackable in sidebar, already supported
- **C. Mark/Flag toggle**: Non-destructive but needs new UI for flags

---

### UXI-5: Confidence Tooltips

**Problem**: Confidence thresholds (40%, 70%) are not explained to users.

**Solution**: Add informative tooltips to confidence badges explaining the calculation.

| Aspect | Details |
|--------|---------|
| Size | XS (<30 min) |
| Risk | None |
| Files | `src/web/templates/review.html` |
| Dependencies | None |

**Rationale for Phase 1**: Trivial effort, high value - improves understanding for all users immediately.

---

## Phase 2: Dropdown Improvements (Medium Priority)

### ~~UXI-4: Recent Metrics Section~~ (DROPPED)

**Status**: DROPPED (2026-01-07)

**Reason**: Redundant with UXI-2 (search). Users can type metric names to filter instantly. The sessionStorage choice also contradicted the business rationale (cross-session use case requires localStorage).

---

### UXI-6: Bulk Action Limit Increase

**Problem**: Bulk actions are capped at 20 candidates. Limiting for large filings.

**Solution**: Increase limit to 50 with chunked API calls.

| Aspect | Details |
|--------|---------|
| Size | S (1-2 hours) |
| Risk | Low |
| Files | `src/web/static/js/review.js`, `src/web/routes/api.py` |
| Dependencies | None |

---

## Phase 3: UX Polish (Lower Priority)

### ~~UXI-8: Focus Management After Navigation~~ (DROPPED)

**Status**: DROPPED (2026-01-07)

**Reason**: The problem statement was inaccurate. Existing keyboard shortcuts (`A`, `R`, `C`, `N`, `P`) already provide immediate keyboard access to all actions - no tabbing required. Additionally, auto-focusing the Accept button would:
1. Bias the review process toward acceptance
2. Potentially harm accessibility (WCAG 2.4.3 Focus Order, 3.2.1 On Focus)
3. Risk accidental submissions if Enter is pressed during page load
4. Skip the natural "read first, then act" workflow

---

### ~~UXI-9: "Other" Rejection Category UX~~ (DROPPED)

**Status**: DROPPED (2026-01-07)

**Reason**: The core requirement (auto-focus textarea) is already implemented for ALL rejection categories in `review.js:846-849`. The proposed helper text ("Please describe why...") would duplicate the existing placeholder ("Why is this not the correct metric?") and label ("Additional Details"). Adding special treatment for "Other" alone creates inconsistent UX.

---

## Dependency Graph

```
Phase 1 (Parallel) - COMPLETE:
├── UXI-1 (Dropdown Keyboard Nav) ✅ ─────────────────────────────┐
├── UXI-2 (Metric Dropdown Search) ✅ ───────────────────────────┼──> Phase 2
├── UXI-3 (Skip Shortcut) ✅ ────────────────────────────────────┤
└── UXI-5 (Confidence Tooltips) ✅ ──────────────────────────────┘

Phase 2 - COMPLETE:
├── UXI-4 (Recent Metrics) ~~DROPPED~~ (redundant with UXI-2)
└── UXI-6 (Bulk Action Limit) ✅ ────────────────────────────────┬──> Phase 3

Phase 3 - ALL DROPPED:
├── UXI-8 (Focus Management) ~~DROPPED~~ (keyboard shortcuts already solve this)
└── UXI-9 ("Other" Rejection UX) ~~DROPPED~~ (auto-focus already implemented for all categories)
```

---

## File Modification Map

| File | UXI-1 | UXI-2 | UXI-3 | UXI-4 | UXI-5 | UXI-6 | UXI-8 | UXI-9 |
|------|-------|-------|-------|-------|-------|-------|-------|-------|
| `review.js` | ✓ | ✓ | ✓ | ✓ | | ✓ | ✓ | ✓ |
| `review.html` | | ✓ | | ✓ | ✓ | | | |
| `api.py` | | | ✓ | | | ✓ | | |

**Conflict Avoidance**:
- UXI-1, UXI-2, UXI-3 all modify `review.js` but different sections (keyboard handlers vs dropdown vs skip)
- UXI-4 dropped - no longer applicable

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Keyboard conflicts with browser | Low | Medium | Use `preventDefault()` carefully, test across browsers |
| Mobile UX degradation | Low | Medium | Test touch interactions, disable keyboard features on mobile |
| Performance with search filtering | Low | Low | Debounce search input, limit DOM updates |
| User confusion with new shortcuts | Low | Low | Keep existing shortcuts, add new ones gradually |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Mouse clicks per decision | ~3-5 | ~1-2 |
| Time to select metric (reclassify) | ~5-10 sec | ~2-3 sec |
| Keyboard-only workflow possible | No | Yes |
| Skip functionality | None | Available |

---

## Execution Order (Recommended)

1. **Phase 1** (Complete): UXI-1 ✅, UXI-2 ✅, UXI-3 ✅, UXI-5 ✅
2. **Phase 2** (Complete): UXI-6 ✅ (UXI-4 dropped)
3. **Phase 3** (Complete): All dropped (UXI-8, UXI-9)

**Workstream Status**: ✅ COMPLETE (6/6 implemented tasks done, 4 dropped)

---

*Last Updated: 2026-01-07*

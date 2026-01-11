# WORKER PROMPT: Task UXI-2-TEST-F4 - Visual Regression E2E Tests

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2-TEST-F4
TASK NAME:     Add visual regression tests with screenshot comparison
WORKSTREAM:    Testing Improvements
SOURCE:        UXI-2-TEST completion evaluation - improvement suggestion #4
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (design 45 min, implementation 90 min, baseline capture 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (additive tests, needs baseline screenshots)
TASK SIZE:     M
DEPENDS ON:    UXI-2-TEST (must be complete)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-2-TEST-F1, UXI-2-TEST-F2, UXI-2-TEST-F3
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add visual regression tests that capture screenshots of the metric dropdown search UI states and compare them against baseline images.

**Business Rationale**: Visual regression testing catches UI changes that functional tests miss - CSS regressions, layout shifts, styling inconsistencies. This ensures the dropdown looks correct, not just functions correctly.

**Current Behavior**: E2E tests verify functionality but not visual appearance.

**Desired Behavior**: Screenshot tests capture dropdown states (empty, filtered, no matches) and flag visual changes.

## Prerequisites

- UXI-2-TEST complete
- Baseline screenshots need to be captured initially

## Files to Create

1. **`tests/e2e/test_metric_dropdown_visual.py`** - Visual regression tests
2. **`tests/e2e/baselines/`** - Directory for baseline screenshots

## Files to Read (Context Only)

- `tests/e2e/conftest.py` - Existing selectors
- Playwright MCP `browser_take_screenshot` documentation

## Implementation Requirements

### Core Functionality

1. **Screenshot Capture Tests**
   - `test_dropdown_closed_screenshot` - Reclassify button in closed state
   - `test_dropdown_open_screenshot` - Dropdown open with all metrics
   - `test_dropdown_filtered_screenshot` - Dropdown with "arr" filter (1 result)
   - `test_dropdown_no_matches_screenshot` - Dropdown showing "No matching metrics"

2. **Screenshot Storage**
   - Save to `tests/e2e/screenshots/` directory
   - Naming convention: `{test_name}_{timestamp}.png`
   - Baseline images in `tests/e2e/baselines/`

3. **Comparison Logic**
   - Document manual comparison process (Playwright MCP doesn't have built-in diff)
   - Suggest using external tool (e.g., `pixelmatch`, `ImageMagick compare`)
   - Or manual visual inspection for initial implementation

### Screenshot Specifications

- Capture dropdown element only (not full page)
- Consistent viewport size (1280x720)
- Use PNG format for lossless comparison

## Test Requirements

### Test Categories (4 tests)

1. **Closed State** (1 test)
   - Reclassify button appearance

2. **Open States** (3 tests)
   - Full dropdown with all metrics
   - Filtered dropdown (1 result)
   - Empty state with "No matching metrics"

## Acceptance Criteria

- [ ] 4 visual test functions documented
- [ ] Baseline directory created
- [ ] Screenshot naming convention documented
- [ ] Comparison process documented (manual or tool-based)
- [ ] Tests capture dropdown element only

## Do NOT

- Modify production CSS/styling
- Add heavy image processing dependencies
- Block on automated comparison (manual comparison OK for v1)

## Verification Commands

```bash
# Verify test file syntax
python3 -c "import tests.e2e.test_metric_dropdown_visual"

# Verify baselines directory exists
ls -la tests/e2e/baselines/
```

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6

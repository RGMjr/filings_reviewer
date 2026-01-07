# WORKER PROMPT: Task UXI-5 - Confidence Tooltips

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-5
TASK NAME:     Add explanatory tooltips to confidence badges
WORKSTREAM:    UX Improvements
SOURCE:        docs/UX_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: <30 min
TIME ACTUAL:   N/A
RISK LEVEL:    None (additive HTML attributes only)
TASK SIZE:     XS
DEPENDS ON:    None
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-1, UXI-2, UXI-3 (Phase 1)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add informative tooltips to confidence badges explaining what the thresholds mean.

**Business Rationale**: Confidence badges show "High (70%+)", "Medium (40-70%)", "Low (<40%)" but reviewers don't know what confidence represents or how to interpret it.

**Current Behavior**: Badges show threshold ranges but no explanation of meaning.

**Desired Behavior**: Hovering over confidence badge shows tooltip explaining confidence is based on keyword proximity, pattern matching, and context features.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/web/templates/review.html`** - Add `title` attributes to confidence badges

## Implementation Requirements

### Core Functionality

1. **Add Tooltip Text**
   - High confidence: "Strong keyword match with nearby value. High likelihood of correct metric."
   - Medium confidence: "Moderate match or distant keyword. Review context carefully."
   - Low confidence: "Weak signals or conflicting features. May be false positive."

2. **Implementation**
   - Use HTML `title` attribute (native tooltip)
   - OR use Bootstrap tooltip if already initialized on page

### Error Handling

- None required (static HTML)

## Acceptance Criteria

- [ ] Hovering over confidence badge shows explanatory tooltip
- [ ] Different text for High/Medium/Low thresholds
- [ ] Tooltip visible in all major browsers

## Do NOT

- Add JavaScript for tooltip functionality (use native or existing Bootstrap)
- Change confidence calculation logic
- Modify badge styling

## Verification Commands

```bash
# Start dev server and verify tooltips appear on hover
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -m flask --app src.web.app run --debug
```

## Critical Evaluation Phase

**Depth: Quick scan (XS task)** - Check for obvious issues only.

## Reference

- **Plan document**: `docs/UX_IMPROVEMENT_PLAN.md`

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

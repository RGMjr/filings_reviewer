# WORKER PROMPT: Task IMG-0-3 - Discovery Decision Report

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-0-3
TASK NAME:     Synthesize discovery findings into go/no-go recommendation
WORKSTREAM:    Image Extraction Discovery
SOURCE:        .claude/plans/flickering-tumbling-kernighan.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1 hour (synthesis: 30 min, recommendation: 15 min, documentation: 15 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (documentation only)
TASK SIZE:     S
DEPENDS ON:    IMG-0-2
UNLOCKS:       Phase 1 (if GO decision)
BLOCKS:        All Phase 1+ tasks
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Synthesize findings from IMG-0-1 and IMG-0-2 into a formal decision document with clear go/no-go recommendation for the image extraction feature.

**Business Rationale**: Before committing engineering resources to Phase 1-6, leadership needs a clear recommendation based on data. This document provides the decision basis.

**Current Behavior**: We have raw data (IMG-0-1) and analysis (IMG-0-2) but no synthesized recommendation.

**Desired Behavior**: A decision document that clearly states: proceed with image extraction, do not proceed, or proceed with modified scope.

## Prerequisites

- IMG-0-1 complete (discovery script run)
- IMG-0-2 complete (sample analysis done)

## Files to Create

1. **`docs/analysis/IMG-0-3_DISCOVERY_DECISION.md`** - Formal decision document

## Files to Read (Context Only)

- `data/discovery/chart_image_inventory.csv` - Quantitative data from IMG-0-1
- `data/discovery/chart_image_analysis.csv` - Classification data from IMG-0-2
- `docs/analysis/IMG-0-2_CHART_ANALYSIS.md` - Qualitative findings
- `.claude/plans/flickering-tumbling-kernighan.md` - Original plan and cost estimates

## Decision Document Structure

```markdown
# Image Extraction Feature: Discovery Decision

**Date**: YYYY-MM-DD
**Author**: [Name]
**Status**: [GO | NO-GO | CONDITIONAL]

## Executive Summary

[2-3 sentence summary of decision and key rationale]

## Discovery Findings Summary

### Quantitative (IMG-0-1)
- Total filings analyzed: N
- Filings with chart images: N (X%)
- Total chart images found: N
- Average per filing: X.X

### Qualitative (IMG-0-2)
- Sample size: N images
- Chart type distribution: [table]
- % with extractable metrics: X%
- % with unique values (not in text): Y%
- Extraction difficulty: Easy X% / Medium Y% / Hard Z%

## ROI Analysis

### Potential Value
- Unique metrics recoverable: ~N per filing
- Filings that would benefit: N (X% of corpus)
- Estimated annual value: [qualitative assessment]

### Implementation Cost
- Phase 1-6 estimated effort: [from plan]
- Vision LLM cost estimate: $X per filing
- Ongoing maintenance: [estimate]

### ROI Assessment
[Value vs cost analysis]

## Recommendation

### Decision: [GO | NO-GO | CONDITIONAL]

### Rationale
[3-5 bullet points explaining the decision]

### If GO: Recommended Scope
- Priority chart types: [list]
- Suggested Phase 1 modifications: [if any]
- Success criteria for Phase 1: [metrics]

### If NO-GO: Reason
[Why not proceeding is the right choice]

### If CONDITIONAL: Conditions
[What conditions must be met to proceed]

## Next Steps

1. [Action 1]
2. [Action 2]
3. [Action 3]

## Appendix: Raw Data References

- Discovery inventory: `data/discovery/chart_image_inventory.csv`
- Analysis spreadsheet: `data/discovery/chart_image_analysis.csv`
- Detailed analysis: `docs/analysis/IMG-0-2_CHART_ANALYSIS.md`
```

## Decision Criteria

**GO if**:
- >=30% of filings contain chart images with extractable metrics
- >=20% of chart values are unique (not in text)
- >=50% of valuable charts are Easy/Medium extraction difficulty
- ROI is positive (value > implementation cost)

**NO-GO if**:
- <10% of filings have valuable chart images
- <10% of chart values are unique
- >70% of charts are Hard extraction difficulty
- Most charts are pie charts or infographics (low CMASB value)

**CONDITIONAL if**:
- Metrics are borderline
- Specific chart types are valuable but others are not
- Scope reduction could make it viable

## Acceptance Criteria

- [ ] Decision document follows template structure
- [ ] All quantitative findings from IMG-0-1 included
- [ ] All qualitative findings from IMG-0-2 included
- [ ] ROI analysis completed
- [ ] Clear GO/NO-GO/CONDITIONAL recommendation
- [ ] Rationale documented with specific data points
- [ ] Next steps defined regardless of decision
- [ ] Appendix references all source data

## Do NOT

- Make decision without IMG-0-1 and IMG-0-2 data
- Proceed to Phase 1 implementation (this is decision only)
- Modify the original plan file (document decision separately)
- Delete discovery data files

## Verification Commands

```bash
# Verify decision document exists
cat docs/analysis/IMG-0-3_DISCOVERY_DECISION.md

# Verify all sections present
grep -c "^##" docs/analysis/IMG-0-3_DISCOVERY_DECISION.md  # Should be >=8
```

---

**Last Updated**: 2026-01-11
**Format Version**: 2.6

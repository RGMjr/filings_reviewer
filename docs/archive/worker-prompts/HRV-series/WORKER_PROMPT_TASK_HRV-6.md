# WORKER PROMPT: Task HRV-6 - Analysis and Pattern Documentation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-6
TASK NAME:     Synthesize findings into actionable improvement recommendations
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (analysis 90 min, documentation 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None - Analysis and documentation only
TASK SIZE:     M
DEPENDS ON:    HRV-3, HRV-4, HRV-5 (all reviews complete)
UNLOCKS:       Phase 5 tasks (if needed), future development priorities
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Synthesize all findings from HRV-3, HRV-4, and HRV-5 into a comprehensive validation report with prioritized improvement recommendations and update the GOLDMINE_REMEDIATION_PLAN with Phase 5 tasks.

**Business Rationale**: Individual filing reviews identify patterns, but synthesis across all filings reveals systemic issues and priorities. This analysis drives the next phase of development by quantifying which improvements will have the highest impact.

**Current Behavior**: Individual filing validation reports exist but are not synthesized. No prioritized improvement roadmap.

**Desired Behavior**: Single comprehensive report with:
- Overall precision/recall metrics
- Prioritized FP patterns (by frequency across filings)
- Prioritized FN patterns (by impact)
- Specific improvement recommendations with effort estimates

## Prerequisites

- HRV-3 complete (Slack validation report)
- HRV-4 complete (Farfetch validation report)
- HRV-5 complete (new filings review)
- All review decisions in database

## Files to Create

1. **`docs/analysis/HRV_VALIDATION_REPORT.md`** - Comprehensive validation report

## Files to Modify

1. **`docs/GOLDMINE_REMEDIATION_PLAN.md`** - Add Phase 5 tasks based on findings

## Files to Read (Context Only)

- `docs/analysis/HRV-3_SLACK_VALIDATION.md` - Slack patterns
- `docs/analysis/HRV-4_FARFETCH_VALIDATION.md` - Farfetch patterns
- `docs/analysis/HRV-5_NEW_FILINGS_REVIEW.md` - New filing patterns
- `docs/GOLDMINE_REMEDIATION_PLAN.md` - Current plan structure

## Implementation Requirements

### Analysis Tasks

1. **Aggregate Metrics Across All Filings**
   ```
   For each filing:
   - Run validation script
   - Collect TP, FP, FN counts
   - Calculate precision, recall, F1

   Aggregate:
   - Weighted average precision/recall (by candidate count)
   - Min/max precision/recall across filings
   - Standard deviation
   ```

2. **Consolidate FP Patterns**
   - Review FP patterns from each filing validation report
   - Group similar patterns across filings
   - Count frequency (how many filings exhibit pattern)
   - Prioritize by: frequency × average occurrences per filing

3. **Consolidate FN Patterns**
   - Review FN patterns from each filing validation report
   - Group similar patterns across filings
   - Count frequency
   - Prioritize by: impact (missed metric value/importance)

4. **Generate Improvement Recommendations**
   - For each top FP pattern: recommend keyword exclusion or filter rule
   - For each top FN pattern: recommend keyword addition or threshold change
   - Estimate effort for each recommendation (XS/S/M/L)

### Validation Report Structure

Create `docs/analysis/HRV_VALIDATION_REPORT.md`:

```markdown
# Human Review Validation Report

**Report Date**: [DATE]
**Validation Period**: [DATE range of reviews]
**Author**: [Name/Claude]

## Executive Summary

The Human Review Validation workstream (HRV) reviewed [N] filings containing
[N] review candidates, comparing against [N] gold standard metrics. Key findings:

- **Overall Precision**: [X]% (target: ≥90%)
- **Overall Recall**: [X]% (target: ≥80%)
- **Gold Standard Expansion**: [N] → [N] metrics (+[N])
- **Top FP Pattern**: [Name] ([N]% of all FPs)
- **Top FN Pattern**: [Name] ([N] metrics missed)

**Production Recommendation**: [APPROVED / NEEDS IMPROVEMENT]

## Section 1: Summary Metrics

### Per-Filing Results

| Filing | Company | Industry | Candidates | Precision | Recall | F1 |
|--------|---------|----------|------------|-----------|--------|-----|
| 2 | Slack | Enterprise SaaS | [N] | [X]% | [X]% | [X]% |
| 1 | Farfetch | Fashion E-commerce | [N] | [X]% | [X]% | [X]% |
| 39 | Snowflake | Cloud SaaS | [N] | [X]% | [X]% | [X]% |
| 40 | DocuSign | Enterprise SaaS | [N] | [X]% | [X]% | [X]% |
| 33 | Snap | Social Media | [N] | [X]% | [X]% | [X]% |
| 38 | Samsara | IoT | [N] | [X]% | [X]% | [X]% |
| **Overall** | - | - | [N] | [X]% | [X]% | [X]% |

### Comparison to Baseline (GR-18)

| Metric | GR-18 Baseline | HRV Result | Change |
|--------|----------------|------------|--------|
| Precision | [X]% | [X]% | [+/-X]pp |
| Recall | [X]% | [X]% | [+/-X]pp |
| Filings Validated | 2 | 6 | +4 |
| Gold Standard Metrics | 108 | [N] | +[N] |

## Section 2: False Positive Analysis

### Summary
- Total False Positives: [N]
- FP Rate: [X]%
- Filings with highest FP rate: [List]

### Top 5 FP Patterns (Prioritized by Impact)

#### 1. [Pattern Name]
**Frequency**: [N] occurrences across [N] filings
**Impact**: [X]% of all FPs
**Examples**:
- Filing 2: "[example quote]"
- Filing 1: "[example quote]"
**Root Cause**: [Technical explanation]
**Fix Recommendation**: [Specific fix]
**Effort**: [XS/S/M/L]

#### 2. [Pattern Name]
...

[Repeat for patterns 3-5]

### Additional FP Patterns (Lower Priority)
- [Pattern 6]: [Brief description], [N] occurrences
- [Pattern 7]: [Brief description], [N] occurrences
...

## Section 3: False Negative Analysis

### Summary
- Total False Negatives: [N]
- FN Rate: [X]%
- Filings with highest FN rate: [List]

### Top 5 FN Patterns (Prioritized by Impact)

#### 1. [Pattern Name]
**Frequency**: [N] missed metrics across [N] filings
**Impact**: [Description of what's being missed]
**Examples**:
- "[gold standard entry 1]"
- "[gold standard entry 2]"
**Root Cause**: [Technical explanation]
**Fix Recommendation**: [Specific fix]
**Effort**: [XS/S/M/L]

#### 2. [Pattern Name]
...

[Repeat for patterns 3-5]

### Additional FN Patterns (Lower Priority)
- [Pattern 6]: [Brief description], [N] occurrences
- [Pattern 7]: [Brief description], [N] occurrences
...

## Section 4: Industry Insights

### Cross-Industry Patterns
- [Pattern seen across all industries]
- [Common metric types detected well]
- [Common metric types missed]

### Industry-Specific Insights

#### Enterprise SaaS (Slack, DocuSign)
- [Pattern or insight]
- [Keyword recommendation]

#### Cloud SaaS (Snowflake)
- [Pattern or insight]
- [Keyword recommendation]

#### E-commerce (Farfetch)
- [Pattern or insight]
- [Keyword recommendation]

#### Social Media (Snap)
- [Pattern or insight]
- [Keyword recommendation]

#### IoT (Samsara)
- [Pattern or insight]
- [Keyword recommendation]

## Section 5: Recommendations

### Prioritized Improvement List

| Priority | ID | Description | Fixes | Effort | Expected Impact |
|----------|-----|-------------|-------|--------|-----------------|
| 1 | GR-19 | [Description] | FP-1, FP-2 | S | -[X]pp FP rate |
| 2 | GR-20 | [Description] | FN-1 | M | +[X]pp recall |
| 3 | GR-21 | [Description] | FN-2, FN-3 | M | +[X]pp recall |
| 4 | GR-22 | [Description] | FP-3 | XS | -[X]pp FP rate |
| 5 | GR-23 | [Description] | FN-4 | L | +[X]pp recall |

### Phase 5 Tasks (for GOLDMINE_REMEDIATION_PLAN)

Based on this analysis, the following tasks should be added to Phase 5:

1. **GR-19**: [Task name and brief description]
2. **GR-20**: [Task name and brief description]
3. **GR-21**: [Task name and brief description]
...

## Appendix A: Methodology

[Describe how validation was performed, matching criteria, etc.]

## Appendix B: Raw Data

[Link to or include raw validation output data]
```

### GOLDMINE_REMEDIATION_PLAN Update

Add Phase 5 section after Phase 4:

```markdown
### Phase 5: Pattern Improvements (from HRV Analysis)

**Prerequisites**: Phase 4 (HRV) complete
**Source**: docs/analysis/HRV_VALIDATION_REPORT.md

#### GR-19: [Task from recommendations]
[Standard task format]

#### GR-20: [Task from recommendations]
[Standard task format]
...
```

### Error Handling

- **Missing Input Files**: Error with list of missing prerequisites
- **Inconsistent Data**: Note discrepancies, use best available data
- **Low Sample Size**: Note confidence limitations in report

## Test Requirements

### No Automated Tests Required

This is an analysis task. Validation is via:
1. Report completeness (all sections present)
2. Metrics internally consistent
3. Recommendations are actionable
4. GOLDMINE_REMEDIATION_PLAN updated

## Acceptance Criteria

- [ ] `docs/analysis/HRV_VALIDATION_REPORT.md` created
- [ ] Report contains all 5 sections plus appendices
- [ ] Overall precision/recall calculated and documented
- [ ] Top 5 FP patterns documented with examples
- [ ] Top 5 FN patterns documented with examples
- [ ] Prioritized improvement recommendations provided
- [ ] Effort estimates for each recommendation
- [ ] Industry-specific insights documented
- [ ] `docs/GOLDMINE_REMEDIATION_PLAN.md` updated with Phase 5 tasks
- [ ] Phase 5 tasks follow standard task format

## Do NOT

- Fabricate data (use actual validation results)
- Skip any of the 5 required sections
- Recommend fixes without effort estimates
- Add Phase 5 tasks without corresponding report findings

## Verification Commands

```bash
# Verify validation report exists and has content
wc -l docs/analysis/HRV_VALIDATION_REPORT.md
# Should be 200+ lines

# Verify all sections present
grep -c "## Section" docs/analysis/HRV_VALIDATION_REPORT.md
# Should be 5

# Verify Phase 5 added to GOLDMINE_REMEDIATION_PLAN
grep "Phase 5" docs/GOLDMINE_REMEDIATION_PLAN.md

# Verify recommendations section has priorities
grep -c "Priority" docs/analysis/HRV_VALIDATION_REPORT.md
# Should be 5+

# Verify FP patterns documented
grep -c "FP Pattern" docs/analysis/HRV_VALIDATION_REPORT.md
# Should be 5+

# Verify FN patterns documented
grep -c "FN Pattern" docs/analysis/HRV_VALIDATION_REPORT.md
# Should be 5+
```

## Expected Impact

**Before HRV-6**:
- Individual filing reports not synthesized
- No prioritized improvement roadmap
- No clear next steps

**After HRV-6**:
- Comprehensive validation report
- Quantified FP/FN patterns
- Prioritized Phase 5 tasks
- Clear development priorities

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: HRV-3, HRV-4, HRV-5
- **Related**: GOLDMINE_REMEDIATION_PLAN.md (Phase 5)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4

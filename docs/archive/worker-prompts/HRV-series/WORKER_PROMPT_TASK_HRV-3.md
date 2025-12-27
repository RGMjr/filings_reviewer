# WORKER PROMPT: Task HRV-3 - Review Slack Filing (Validation)

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-3
TASK NAME:     Review all Slack candidates against 38 known gold standard metrics
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (review ~60-80 candidates, document patterns)
TIME ACTUAL:   N/A
RISK LEVEL:    None - Manual review task, no code changes
TASK SIZE:     M
DEPENDS ON:    HRV-2 (need validation scripts)
UNLOCKS:       HRV-5 (learn patterns before expanding), HRV-6 (analysis input)
BLOCKS:        None
PARALLEL WITH: HRV-4
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Review all review candidates for the Slack S-1 filing using the web interface, comparing against the 38 known gold standard metrics. Document false positive and false negative patterns.

**Business Rationale**: Slack has the most complete gold standard labeling (38 metrics). Validating against this filing establishes baseline precision/recall and identifies systematic issues before expanding to other filings.

**Current Behavior**: 38 metrics manually identified in gold standard CSV. Unknown how many system detects and accuracy.

**Desired Behavior**: All Slack candidates reviewed with accept/reject decisions. Precision/recall calculated. FP/FN patterns documented.

## Prerequisites

- HRV-2 complete (validation scripts available)
- Database has Slack filing (filing_id=2)
- Review candidates generated for Slack
- Web review interface functional

## Files to Modify

- None (manual review task)

## Files to Create

1. **`docs/analysis/HRV-3_SLACK_VALIDATION.md`** - Validation results and patterns

## Files to Read (Context Only)

- `data/gold_standard/golden_set_251218.csv` - 38 Slack metrics (filter by company="Slack")
- `docs/HUMAN_REVIEW_VALIDATION_PLAN.md` - Review workflow

## Implementation Requirements

### Review Workflow

1. **Generate Candidates** (if not already done)
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/generate_review_candidates.py --filing-id 2
   ```

2. **Start Web Interface**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python -m src.web.app
   # Open http://localhost:8000
   ```

3. **Review Each Candidate**
   - Navigate to Slack filing in web interface
   - For each candidate:
     - Compare against gold standard CSV (open in separate window)
     - If matches a gold standard metric: **Accept**
     - If NOT in gold standard: **Reject** and note pattern
     - Use notes field for observations

4. **Run Validation Script**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/validate_against_gold_standard.py --filing-id 2
   ```

5. **Document Results** in `docs/analysis/HRV-3_SLACK_VALIDATION.md`

### Gold Standard Reference

Filter Slack metrics from CSV:
```bash
grep -i "slack" data/gold_standard/golden_set_251218.csv | wc -l
# Expected: 38 rows
```

Key metrics to look for:
- DAU (Daily Active Users)
- Paid Customers
- Revenue metrics
- Messages sent
- Connected apps

### Documentation Requirements

Create `docs/analysis/HRV-3_SLACK_VALIDATION.md` with:

```markdown
# HRV-3: Slack Filing Validation Results

**Filing**: Slack S-1 (filing_id=2)
**Reviewed**: [DATE]
**Gold Standard Metrics**: 38

## Summary Metrics

| Metric | Value |
|--------|-------|
| Review Candidates | [N] |
| Accepted | [N] |
| Rejected | [N] |
| True Positives | [N] |
| False Positives | [N] |
| False Negatives | [N] |
| Precision | [X]% |
| Recall | [X]% |
| F1 Score | [X]% |

## False Positive Patterns

### Pattern 1: [Name]
**Frequency**: [N] occurrences
**Example**: "[quote from segment]"
**Why FP**: [explanation]
**Fix Recommendation**: [keyword exclusion, filter rule, etc.]

### Pattern 2: [Name]
...

## False Negative Patterns

### Pattern 1: [Name]
**Frequency**: [N] occurrences
**Example**: "[quote from gold standard]"
**Why Missed**: [explanation]
**Fix Recommendation**: [new keyword, pattern addition, etc.]

### Pattern 2: [Name]
...

## Observations

- [General observations about system performance]
- [Segment type distribution of FPs]
- [Common characteristics of missed metrics]

## Recommendations

1. [Prioritized recommendation 1]
2. [Prioritized recommendation 2]
3. [Prioritized recommendation 3]
```

### Error Handling

- **Missing Candidates**: Generate before starting review
- **Interface Errors**: Document and report, don't block on technical issues
- **Ambiguous Cases**: Mark as rejected, note in observations

## Test Requirements

### No Automated Tests Required

This is a manual review task. Validation is via:
1. All candidates have decisions (no pending)
2. Validation script produces metrics
3. Documentation complete

## Acceptance Criteria

- [ ] All Slack review candidates have accept/reject decisions
- [ ] Validation script runs successfully
- [ ] Precision calculated and documented (target: ≥90%)
- [ ] Recall calculated and documented (target: ≥80%)
- [ ] Minimum 3 FP patterns documented with examples
- [ ] Minimum 3 FN patterns documented with examples
- [ ] Fix recommendations provided for top patterns
- [ ] `docs/analysis/HRV-3_SLACK_VALIDATION.md` created

## Do NOT

- Modify gold standard CSV
- Modify source code
- Skip candidates (review all)
- Rush through without documenting patterns

## Verification Commands

```bash
# Verify all candidates reviewed
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  psql -c "
    SELECT
      COUNT(*) as total_candidates,
      COUNT(rd.id) as reviewed,
      COUNT(*) - COUNT(rd.id) as pending
    FROM review_candidates rc
    LEFT JOIN review_decisions rd ON rc.id = rd.candidate_id
    WHERE rc.filing_id = 2
  "

# Run validation
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/validate_against_gold_standard.py --filing-id 2

# Verify documentation exists
ls docs/analysis/HRV-3_SLACK_VALIDATION.md
```

## Expected Impact

**Before HRV-3**:
- Unknown precision/recall on Slack
- No documented FP/FN patterns
- No baseline for improvement

**After HRV-3**:
- Quantified precision/recall vs gold standard
- Systematic FP patterns identified
- Systematic FN patterns identified
- Input for HRV-6 analysis

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: HRV-2
- **Related**: HRV-4 (parallel), HRV-6 (synthesis)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4

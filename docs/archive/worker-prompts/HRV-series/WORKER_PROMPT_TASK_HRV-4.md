# WORKER PROMPT: Task HRV-4 - Review Farfetch Filing (Validation)

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-4
TASK NAME:     Review all Farfetch candidates against 67 known gold standard metrics
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3-4 hours (review ~100-120 candidates, document patterns)
TIME ACTUAL:   N/A
RISK LEVEL:    None - Manual review task, no code changes
TASK SIZE:     L
DEPENDS ON:    HRV-2 (need validation scripts)
UNLOCKS:       HRV-5 (learn patterns before expanding), HRV-6 (analysis input)
BLOCKS:        None
PARALLEL WITH: HRV-3
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Review all review candidates for the Farfetch F-1 filing using the web interface, comparing against the 67 known gold standard metrics. Document false positive and false negative patterns, with focus on fashion/luxury e-commerce industry patterns.

**Business Rationale**: Farfetch has the largest gold standard coverage (67 metrics) and represents the fashion/luxury e-commerce industry. Validating this filing provides robust FP/FN patterns and tests system performance on larger filings.

**Current Behavior**: 67 metrics manually identified in gold standard CSV. Unknown how many system detects and accuracy.

**Desired Behavior**: All Farfetch candidates reviewed with accept/reject decisions. Precision/recall calculated. Industry-specific patterns documented.

## Prerequisites

- HRV-2 complete (validation scripts available)
- Database has Farfetch filing (filing_id=1)
- Review candidates generated for Farfetch
- Web review interface functional

## Files to Modify

- None (manual review task)

## Files to Create

1. **`docs/analysis/HRV-4_FARFETCH_VALIDATION.md`** - Validation results and patterns

## Files to Read (Context Only)

- `data/gold_standard/golden_set_251218.csv` - 67 Farfetch metrics (filter by company="Farfetch")
- `docs/HUMAN_REVIEW_VALIDATION_PLAN.md` - Review workflow
- `docs/analysis/HRV-3_SLACK_VALIDATION.md` - Compare patterns with Slack (if available)

## Implementation Requirements

### Review Workflow

1. **Generate Candidates** (if not already done)
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/generate_review_candidates.py --filing-id 1
   ```

2. **Start Web Interface**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python -m src.web.app
   # Open http://localhost:8000
   ```

3. **Review Each Candidate**
   - Navigate to Farfetch filing in web interface
   - For each candidate:
     - Compare against gold standard CSV
     - Accept matches, reject non-matches with pattern notes
     - Pay attention to industry-specific terminology

4. **Run Validation Script**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/validate_against_gold_standard.py --filing-id 1
   ```

5. **Document Results** in `docs/analysis/HRV-4_FARFETCH_VALIDATION.md`

### Gold Standard Reference

Filter Farfetch metrics from CSV:
```bash
grep -i "farfetch" data/gold_standard/golden_set_251218.csv | wc -l
# Expected: 67 rows
```

Key metrics to look for (fashion/e-commerce specific):
- GMV (Gross Merchandise Value)
- Active Consumers
- Orders
- AOV (Average Order Value)
- Platform take rate
- Partner boutiques
- Revenue per consumer

### Industry-Specific Considerations

**Fashion E-commerce Terms**:
- "Boutiques" and "Brand Partners" (not traditional customers)
- GMV vs Revenue distinction
- Take rate / platform fee
- Luxury goods vs mass market terminology
- Geographic segments (EMEA, Americas, APAC)

### Documentation Requirements

Create `docs/analysis/HRV-4_FARFETCH_VALIDATION.md` with:

```markdown
# HRV-4: Farfetch Filing Validation Results

**Filing**: Farfetch F-1 (filing_id=1)
**Industry**: Fashion/Luxury E-commerce
**Reviewed**: [DATE]
**Gold Standard Metrics**: 67

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

## Comparison with Slack (HRV-3)

| Metric | Slack | Farfetch | Difference |
|--------|-------|----------|------------|
| Precision | [X]% | [X]% | [+/-X]pp |
| Recall | [X]% | [X]% | [+/-X]pp |
| F1 Score | [X]% | [X]% | [+/-X]pp |

## False Positive Patterns

### Pattern 1: [Name]
**Frequency**: [N] occurrences
**Example**: "[quote from segment]"
**Why FP**: [explanation]
**Fix Recommendation**: [keyword exclusion, filter rule, etc.]
**Also seen in Slack?**: [Yes/No]

### Pattern 2: [Name]
...

## False Negative Patterns

### Pattern 1: [Name]
**Frequency**: [N] occurrences
**Example**: "[quote from gold standard]"
**Why Missed**: [explanation]
**Fix Recommendation**: [new keyword, pattern addition, etc.]
**Also seen in Slack?**: [Yes/No]

### Pattern 2: [Name]
...

## Industry-Specific Patterns

### Fashion/E-commerce Terminology
- [Pattern unique to fashion industry]
- [GMV vs Revenue handling]
- [Boutique/partner terminology]

### Table Structure Observations
- [How fashion metrics appear in tables]
- [Multi-period comparisons]

## Observations

- [General observations about system performance]
- [Differences from Slack patterns]
- [Segment type distribution of FPs]

## Recommendations

1. [Prioritized recommendation 1]
2. [Prioritized recommendation 2]
3. [Prioritized recommendation 3]
```

### Error Handling

- **Large Filing Issues**: Farfetch is larger than Slack; may need to paginate in UI
- **Complex Tables**: E-commerce filings often have dense tables; pay attention to table FPs
- **Ambiguous Cases**: Mark as rejected, note in observations

## Test Requirements

### No Automated Tests Required

This is a manual review task. Validation is via:
1. All candidates have decisions (no pending)
2. Validation script produces metrics
3. Documentation complete with industry-specific analysis

## Acceptance Criteria

- [ ] All Farfetch review candidates have accept/reject decisions
- [ ] Validation script runs successfully
- [ ] Precision calculated and documented (target: ≥85%)
- [ ] Recall calculated and documented (target: ≥75%)
- [ ] Minimum 3 FP patterns documented with examples
- [ ] Minimum 3 FN patterns documented with examples
- [ ] Industry-specific (fashion/e-commerce) patterns documented
- [ ] Comparison with Slack patterns included
- [ ] Fix recommendations provided for top patterns
- [ ] `docs/analysis/HRV-4_FARFETCH_VALIDATION.md` created

## Do NOT

- Modify gold standard CSV
- Modify source code
- Skip candidates (review all)
- Ignore industry-specific terminology differences

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
    WHERE rc.filing_id = 1
  "

# Run validation
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/validate_against_gold_standard.py --filing-id 1

# Verify documentation exists
ls docs/analysis/HRV-4_FARFETCH_VALIDATION.md

# Compare with Slack metrics
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/validate_against_gold_standard.py --all
```

## Expected Impact

**Before HRV-4**:
- Unknown precision/recall on Farfetch
- No industry-specific pattern analysis
- No comparison across filings

**After HRV-4**:
- Quantified precision/recall vs gold standard
- Fashion/e-commerce patterns identified
- Cross-filing pattern comparison
- Input for HRV-6 analysis

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: HRV-2
- **Related**: HRV-3 (parallel), HRV-6 (synthesis)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4

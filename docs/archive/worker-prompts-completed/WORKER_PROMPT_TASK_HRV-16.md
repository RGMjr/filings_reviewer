# WORKER PROMPT: Task HRV-16 - Validation Re-run (Post-Phase 4)

```
===============================================================================
TASK ID:       HRV-16
TASK NAME:     Re-run validation against gold standard after Phase 4 improvements
WORKSTREAM:    Human Review Validation (Phase 4e - Final Validation)
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md, docs/PROJECT_TASK_INVENTORY.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1 hour (candidate regeneration 15min, validation 30min, documentation 15min)
TIME ACTUAL:   N/A
RISK LEVEL:    NONE - Read-only analysis task
TASK SIZE:     S
DEPENDS ON:    HRV-22 (HTMLSegmenter bug fix - complete)
UNLOCKS:       None (final validation task in Phase 4)
BLOCKS:        None
PARALLEL WITH: None
===============================================================================
```

## Objective

Re-run validation scripts against the gold standard to measure precision/recall after all Phase 4 improvements (HRV-7 through HRV-22). This is the final validation checkpoint before declaring Phase 4 complete.

**Business Rationale**: Phase 4 implemented 10+ improvements including financial statement filtering, percentage filtering, table row parsing fixes, and HTMLSegmenter bug fixes. We need to quantify the improvement to validate the work and inform future priorities.

**Current Behavior (Baseline from HRV-4)**:
- Farfetch: 10.4% precision, 49.3% recall, F1 17.2%
- 283 false positives, 34 false negatives
- Data quality issues affecting Farfetch segments (fixed in HRV-22)

**Desired Behavior (Targets)**:
- Precision: ≥20% (realistic), ≥30% (stretch)
- Recall: ≥55% (realistic), ≥65% (stretch)
- F1 Score: ≥28% (realistic), ≥40% (stretch)
- Document actual achieved metrics

## Prerequisites

- HRV-22 complete (HTMLSegmenter bug fix + Farfetch re-extraction) ✅
- Database running with updated segment data
- Gold standard CSV available at `data/gold_standard/golden_set_251218.csv`
- Validation scripts available: `scripts/validate_against_gold_standard.py`

## Files to Read (Context Only)

- `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` - Baseline patterns and analysis
- `docs/PROJECT_TASK_INVENTORY.md` - Phase 4 success metrics table
- `data/gold_standard/golden_set_251218.csv` - Gold standard metrics (Farfetch: 67, Slack: 41)

## Files to Create

1. **`docs/analysis/HRV-16_VALIDATION_RESULTS.md`** - Validation results report

## Implementation Requirements

### Core Functionality

1. **Regenerate Review Candidates**
   - Run candidate generation for Farfetch (filing_id=1) and Slack (filing_id=35)
   - Use fresh mode to ensure candidates reflect all Phase 4 changes
   - Record candidate counts for comparison

2. **Run Validation Script**
   - Execute `validate_against_gold_standard.py` for both filings
   - Capture precision, recall, F1 metrics
   - Export false positive and false negative lists

3. **Compare to Baseline**
   - Document delta vs HRV-4 baseline metrics
   - Calculate improvement percentages
   - Note any regressions

4. **Document Results**
   - Create comprehensive validation report
   - Include per-filing breakdown
   - Document remaining FP/FN patterns for future work

### Report Structure

The validation report (`HRV-16_VALIDATION_RESULTS.md`) must include:

1. **Executive Summary**: Pass/fail vs targets, key metrics
2. **Farfetch Results**: Precision, recall, F1, candidate count, comparison to baseline
3. **Slack Results**: Precision, recall, F1, candidate count, comparison to baseline
4. **Combined Metrics**: Weighted average across both filings
5. **Improvement Analysis**: What worked, what didn't
6. **Remaining Issues**: Top FP/FN patterns still present
7. **Recommendations**: Next steps if targets not met

## Acceptance Criteria

- [ ] Review candidates regenerated for Farfetch and Slack
- [ ] Validation script executed successfully for both filings
- [ ] Precision, recall, F1 documented for each filing
- [ ] Comparison to HRV-4 baseline included
- [ ] `docs/analysis/HRV-16_VALIDATION_RESULTS.md` created with all 7 sections
- [ ] PROJECT_TASK_INVENTORY.md updated with final Phase 4 metrics
- [ ] Clear pass/fail determination against targets

## Do NOT

- Modify any extraction or review code (this is analysis only)
- Change gold standard CSV data
- Skip documenting results even if targets are not met
- Make changes to "fix" issues discovered (create follow-up tasks instead)

## Verification Commands

```bash
# Regenerate candidates for Farfetch
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/generate_review_candidates.py --filing-id 1 --fresh

# Regenerate candidates for Slack
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/generate_review_candidates.py --filing-id 35 --fresh

# Run validation for all filings with gold standard
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal gold standard test
pytest -m gold_standard --gold-standard-mode=fresh -v
```

## Critical Evaluation Phase

**Task Size: S** - Standard evaluation (quick checklist review)

After running validation:
1. Verify all metrics are captured accurately
2. Confirm report sections are complete
3. Check comparison math is correct
4. Identify any follow-up tasks needed

### User Approval

Before committing, present results to user:
> "HRV-16 validation complete. Results: [precision]% precision, [recall]% recall, [F1]% F1.
> Target achievement: [PASS/PARTIAL/FAIL]
>
> Should I commit the validation report?"

## Expected Impact

**Before (HRV-4 Baseline)**:
| Metric | Farfetch | Slack | Combined |
|--------|----------|-------|----------|
| Precision | 10.4% | 76% | ~25% |
| Recall | 49.3% | 84% | ~60% |
| F1 | 17.2% | 79.7% | ~35% |

**After (HRV-16 Targets)**:
| Metric | Target (Realistic) | Target (Stretch) |
|--------|-------------------|------------------|
| Precision | ≥20% | ≥30% |
| Recall | ≥55% | ≥65% |
| F1 | ≥28% | ≥40% |

## Reference

- **Issue source**: docs/PROJECT_TASK_INVENTORY.md - Wave 4 Phase 4e
- **Dependencies**: HRV-22 (complete), all Phase 4 improvements
- **Related**: HRV-4 (original Farfetch validation), HRV-6 (pattern analysis)

---

**Last Updated**: 2026-01-04
**Format Version**: 2.6

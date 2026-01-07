# WORKER PROMPT: Task P2-UF-1 - Unit-Based Metric Filtering

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       P2-UF-1
TASK NAME:     Add unit compatibility rules to prevent metric-unit mismatches in candidate generation
WORKSTREAM:    Human Review System Improvements - Phase 2
SOURCE:        Slack filing duplicate candidates analysis (snuggly-watching-micali.md)
STATUS:        🟡 PENDING (DEFERRED - Phase 2)
COMPLETION:    N/A
TIME ESTIMATE: 3-4 hours (analysis 1h, implementation 1.5h, testing 1.5h)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium (could exclude valid edge cases if rules too strict)
TASK SIZE:     M
DEPENDS ON:    DUP-3 (Deduplicator and Helpers Integration)
UNLOCKS:       None (end of this workstream)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add unit compatibility rules to `config/metric_keywords.yaml` to prevent obviously incorrect metric-unit matches (e.g., percentages matching customer count metrics).

**Business Rationale**: In the Slack filing review, retention rate percentages (146%, 149%, 151%) incorrectly matched the "Customers >$100" keyword and generated candidates for `cm_large_customers_period_end`. These are clearly Net Revenue Retention values, not customer counts. This wastes reviewer time and reduces confidence in the system.

**Current Behavior**: Any numeric value near a metric keyword generates a candidate, regardless of whether the value's unit makes sense for that metric.

**Desired Behavior**:
1. Metrics define allowed and/or forbidden unit types
2. Candidate generation filters out unit-incompatible matches
3. Filtering logged for debugging

## Prerequisites

- DUP-1, DUP-2, DUP-3 complete (duplicate prevention working)
- Review Slack filing false positives to identify all unit-metric mismatches

## Pre-Implementation Analysis Required

**IMPORTANT**: Before implementing, conduct this analysis:

1. **Audit current false positives**
   ```sql
   -- Find candidates where human reclassified to different metric
   SELECT
       rc.suggested_metric_id,
       rd.assigned_metric_id,
       rc.parsed_unit,
       COUNT(*) as count
   FROM review_candidates rc
   JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
   WHERE rd.decision = 'reclassify'
   GROUP BY rc.suggested_metric_id, rd.assigned_metric_id, rc.parsed_unit
   ORDER BY count DESC;
   ```

2. **Identify metric-unit rules**
   - Which metrics should NEVER match percentages?
   - Which metrics should ONLY match percentages?
   - Which metrics should NEVER match currency values?
   - Document each rule with examples from actual data

3. **Check for edge cases**
   - Are there valid scenarios where a percentage DOES relate to customer counts?
   - Example: "Customers grew 146% year-over-year" - this IS about customers but IS a percentage
   - Such edge cases should NOT be filtered

## Files to Create

1. **`tests/unit/review/test_unit_filtering.py`** - Unit tests for filtering logic

## Files to Modify

1. **`config/metric_keywords.yaml`** - Add `unit_constraints` to relevant metrics
2. **`src/review/keyword_matching.py`** - Add unit compatibility check
3. **`src/review/candidate_generator.py`** - Apply unit filter during candidate creation

## Files to Read (Context Only)

- `config/metric_keywords.yaml` - Current metric patterns
- `src/review/number_parsing.py` - How units are parsed
- `src/review/candidate_generator.py` - Current candidate generation flow

## Implementation Requirements

### Core Functionality

1. **YAML Configuration Schema**
   ```yaml
   cm_large_customers_period_end:
     patterns:
       - "Paid Customers >$"
       - "Customers >$100"
     unit_constraints:
       forbidden: [percent]  # Never match percentages
       # OR
       allowed: [count, customers]  # Only match these units
   ```

2. **Unit Filtering Logic**
   - Check `parsed_unit` against metric's `unit_constraints`
   - If `forbidden` specified: reject if unit in list
   - If `allowed` specified: reject if unit NOT in list
   - Log filtered candidates at DEBUG level with reason

3. **Affected Metrics** (based on Slack analysis)
   - `cm_large_customers_period_end`: forbidden=[percent]
   - `cm_customers_period_end`: forbidden=[percent]
   - `cm_active_customers_total`: forbidden=[percent]
   - `cm_net_revenue_retention`: allowed=[percent]
   - `cm_churn_rate`: allowed=[percent]
   - (Complete list requires pre-implementation analysis)

### Error Handling

- Missing `unit_constraints` = no filtering (current behavior)
- Unknown unit type = don't filter (conservative)
- Log unexpected unit types at INFO level

### Performance Requirements

- Unit check should be O(1) - simple set membership
- No measurable impact on candidate generation time

## Gold Standard Validation

**This task affects metric identification logic. Gold standard validation is REQUIRED.**

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal validation (must pass before commit)
pytest -m gold_standard --gold-standard-mode=fresh -v
```

### Regression Handling

- If recall drops: unit constraints may be too strict
- Check if filtered candidates were actually valid
- Adjust constraints to be more permissive for edge cases

## Test Requirements

### Coverage Target: **≥ 90%** for new filtering logic

### Test Categories (12+ tests recommended)

1. **Filtering Logic Tests** (4-5 tests)
   - Forbidden unit filtered correctly
   - Allowed unit passes
   - Missing unit_constraints = no filtering
   - Unknown unit type = no filtering

2. **Edge Case Tests** (4-5 tests)
   - NULL parsed_unit handling
   - Empty unit_constraints
   - Metric with both allowed and forbidden (error case?)
   - Very long unit strings

3. **Integration Tests** (3-4 tests)
   - Full candidate generation with unit filtering
   - Filtered candidates logged correctly
   - Gold standard metrics still detected

### Known Edge Cases to Test

- "Customers grew 146%" - percentage about customers (should NOT filter)
- "10% of customers" - percentage describing proportion (context matters)
- Units like "k", "M", "B" for counts

## Acceptance Criteria

- [ ] `unit_constraints` schema added to metric_keywords.yaml
- [ ] At least 5 metrics have unit_constraints defined (based on analysis)
- [ ] Unit filtering applied during candidate generation
- [ ] Filtered candidates logged at DEBUG level
- [ ] **12+ unit tests** covering filtering logic
- [ ] **Test coverage ≥ 90%** for filtering code
- [ ] Gold standard validation passes (no regression)
- [ ] All existing tests still pass
- [ ] Documentation updated in CLAUDE.md

## Do NOT

- Add overly strict rules without data analysis
- Filter edge cases that are actually valid
- Change existing metric patterns (only add unit_constraints)
- Modify deduplication or suppression logic (that's DUP-1/2/3)

## Verification Commands

```bash
# Run new tests
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_unit_filtering.py -v

# Gold standard validation
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Full review module tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Gold Standard Review
- [ ] Precision unchanged or improved
- [ ] Recall unchanged or improved
- [ ] No valid metrics filtered out

### 2. Edge Case Review
- [ ] Reviewed all filtered candidates manually
- [ ] No obvious false negatives introduced
- [ ] Edge cases documented

### 3. User Approval (REQUIRED)
**STOP and ask the user** before committing, especially with:
- List of filtered candidates from test run
- Any edge cases identified
- Proposed adjustments to constraints

## Expected Impact

**Before P2-UF-1**:
- Percentages incorrectly match customer count metrics
- Reviewers waste time rejecting obvious mismatches
- Example: 146% → cm_large_customers_period_end (wrong)

**After P2-UF-1**:
- Percentages filtered from customer count metrics
- Only contextually-appropriate matches presented
- Example: 146% → cm_net_revenue_retention only (correct)

## Reference

- **Issue source**: Slack filing duplicate candidates analysis
- **Dependencies**: DUP-1, DUP-2, DUP-3
- **Related**: cm_net_revenue_retention, cm_large_customers_period_end false matches

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6

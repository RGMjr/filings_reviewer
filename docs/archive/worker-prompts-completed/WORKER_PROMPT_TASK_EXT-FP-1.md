# WORKER PROMPT: Task EXT-FP-1 - Fix cm_billings False Positive Over-Generation

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EXT-FP-1
TASK NAME:     Fix cm_billings metric generating excessive false positives
WORKSTREAM:    Extraction Improvement
SOURCE:        Extraction Quality Analysis (2026-01-13)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (investigation 30 min, implementation 60 min, testing 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Adding exclusions to existing metric pattern
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       EXT-VAL-1 (validation script improvements)
BLOCKS:        None
PARALLEL WITH: EXT-FN-1 (table extraction improvements)
═══════════════════════════════════════════════════════════════════════════════

## Pre-Execution Verification (2026-01-14)

Investigation confirmed:
- **49 cm_billings candidates** still generated from Slack filing
- All candidates come from **one table segment** containing "Calculated Billings"
- The `required_context` gating IS working (segment passes because it contains "calculated billings")
- **Root cause**: Table also contains "Free Cash Flow" and "Adjusted Free Cash Flow" rows; numbers from ALL rows match because "Calculated Billings" appears somewhere in the segment

**Actual table content**:
```
Calculated Billings [CELL] $ [CELL] 143,390 [CELL] $ [CELL] 289,013 ...
Free Cash Flow [CELL] $ [CELL] (114,038 ...
Adjusted Free Cash Flow [CELL] $ [CELL] (106,005 ...
Tender offer payments and repurchases...
```

## Objective

Fix the `cm_billings` metric which is generating 49 false positive candidates on the Slack filing (vs 0 in gold standard). The candidates come from a **single table segment** containing "Calculated Billings" alongside other financial metrics (Free Cash Flow, Adjusted Free Cash Flow). All numbers in the table match cm_billings because the segment passes context gating.

**Business Rationale**: False positives waste reviewer time and reduce trust in the extraction system. 49 FPs represents 50% of all candidates for Slack, dramatically reducing precision.

**Current Behavior**: The `cm_billings` pattern matches any number in a segment containing "billings" or "calculated billings", including:
- Numbers from "Free Cash Flow" rows in the same table
- Numbers from "Adjusted Free Cash Flow" rows
- Numbers from "Tender offer payments" rows
- All numbers in a multi-metric financial table

**Desired Behavior**: `cm_billings` should only match actual billing amounts, not:
- Free Cash Flow figures
- Adjusted Free Cash Flow figures
- Tender offer payments
- Other financial statement line items in the same table

## Prerequisites

- Understanding of `config/metric_keywords.yaml` structure
- Familiarity with HRV-10/HRV-11 financial statement filtering approach

## Files to Modify

1. **`config/metric_keywords.yaml`** - Add exclusion patterns to cm_billings metric
2. **`tests/unit/review/test_keyword_exclusions.py`** - Add tests for new cm_billings exclusions (existing test file for exclusions)

## Files to Read (Context Only)

- `src/review/false_positive_filter.py` - See FINANCIAL_LINE_ITEM_PATTERNS for reference
- `src/review/keyword_matching.py` - See how exclusions are applied
- `data/gold_standard/Slack_Technologies/filing.html` - Understand the source text

## Implementation Requirements

### Core Functionality

1. **Add Exclusion Patterns to cm_billings**
   Add these exclusion patterns to the `cm_billings` section in `metric_keywords.yaml`:
   ```yaml
   cm_billings:
     # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
     <<: *revenue_synonym_context
     patterns:
       - '\bbillings\b'
       - '\btotal\s+billings\b'
       - '\bcalculated\s+billings\b'
       - '\badjusted\s+billings\b'
     exclusions:  # ADD THIS SECTION
       # Cash flow metrics (from Slack table)
       - '\bfree\s+cash\s+flow\b'
       - '\badjusted\s+free\s+cash\s+flow\b'
       - '\bcash\s+flow\b'
       # Tender offer / compensation items
       - '\btender\s+offer\b'
       - '\brepurchases?\s+deemed\s+compensation\b'
       # Revenue line items (general financial statements)
       - '\brevenue\b'
       - '\bdeferred\s+revenue\b'
       - '\bcost\s+of\s+(?:revenue|sales)\b'
       - '\bnet\s+revenue\b'
       # Period markers
       - '\b(?:beginning|end)\s+of\s+period\b'
   ```

2. **Validate Against Slack Filing**
   - After changes, cm_billings candidates for Slack should drop from 49 to **~5** (only legitimate "Calculated Billings" values)
   - The 5 legitimate values are: 143,390 / 289,013 / 516,972 / 102,080 / 149,637

3. **Preserve Legitimate Matches**
   - Numbers on the "Calculated Billings" row should still match
   - The exclusion patterns should filter numbers on OTHER rows (Free Cash Flow, etc.)

### Error Handling

- Patterns must be valid regex (test compilation)
- Exclusions should be comprehensive but not over-broad

## Test Requirements

### Coverage Target: **Maintain existing coverage** for `keyword_matching.py`

### Test Categories (5+ tests recommended)

Add a new test class `TestExclusionPatternBillings` to `tests/unit/review/test_keyword_exclusions.py`:

1. **Exclusion Tests** (4-5 tests)
   - Test that "Free Cash Flow" near "billings" does NOT match cm_billings
   - Test that "Adjusted Free Cash Flow" amounts don't match
   - Test that "revenue" in context excludes cm_billings
   - Test that "tender offer" in context excludes cm_billings
   - Test that "deferred revenue" in context excludes cm_billings

2. **Preservation Tests** (2-3 tests)
   - Test that "calculated billings" still matches cm_billings (no exclusion triggered)
   - Test that "total billings" still matches when no exclusion patterns present
   - Test that billings with cohort context still works

### Known Edge Cases to Test

- Table segments with [CELL] and [ROW] markers containing both "billings" AND "cash flow"
- The actual Slack table structure where multiple metrics appear together

### Specific False Positive Examples (from Slack verification)

These are actual FPs that should be eliminated by the fix:

1. **Free Cash Flow row** (value: 114,038):
   ```
   "Calculated Billings [CELL] ... [ROW] Free Cash Flow [CELL] $ [CELL] (114,038 ..."
   ```

2. **Adjusted Free Cash Flow row** (value: 106,005):
   ```
   "... [ROW] Adjusted Free Cash Flow [CELL] $ [CELL] (106,005 ..."
   ```

3. **Tender offer payments row** (value: 8,033):
   ```
   "... [ROW] Tender offer payments and repurchases deemed compensation(1) [CELL] 8,033 ..."
   ```

After fix:
- Numbers from "Calculated Billings" row should STILL generate candidates (~5 values)
- Numbers from other rows (Free Cash Flow, etc.) should NOT generate candidates

## Gold Standard Validation

This task modifies `config/metric_keywords.yaml`. Gold standard validation is **required** before commit.

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --company "Slack" --mode fresh --baseline

# Verify cm_billings candidates dropped
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer && python3 << 'EOF'
from src.extraction.html_segmenter import segment_filing_html
from src.review.candidate_generator import CandidateGenerator

segments = segment_filing_html(999, 'data/gold_standard/Slack_Technologies/filing.html')
segment_dicts = [s.to_dict() for s in segments]
generator = CandidateGenerator()
candidates = generator.generate_for_filing(999, 999, segment_dicts)
billing_cands = [c for c in candidates if c.suggested_metric_id == 'cm_billings']
print(f'cm_billings candidates: {len(billing_cands)} (target: <5)')
EOF
```

## Acceptance Criteria

- [ ] `cm_billings` exclusion patterns added to `metric_keywords.yaml`
- [ ] Slack filing cm_billings candidates reduced from 49 to ~5 (only legitimate "Calculated Billings" values)
- [ ] No regression in gold standard metrics (precision/recall maintained)
- [ ] **5+ unit tests** in `test_keyword_exclusions.py` covering exclusion and preservation scenarios
- [ ] All existing tests still pass
- [ ] Gold standard validation passes

## Do NOT

- Modify `src/review/false_positive_filter.py` - use YAML exclusions only
- Remove the `required_context` constraint - it should remain in addition to exclusions
- Change patterns for other metrics
- Over-broaden exclusions (keep them specific to financial statement line items)
- Add exclusions that would filter out legitimate "Calculated Billings" values

## Verification Commands

```bash
# Run keyword exclusion tests (including new cm_billings tests)
python3 -m pytest tests/unit/review/test_keyword_exclusions.py -v

# Verify cm_billings candidates dropped (target: ~5, down from 49)
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer && python3 << 'EOF' 2>&1 | grep -v "HRV-22"
from src.extraction.html_segmenter import segment_filing_html
from src.review.candidate_generator import CandidateGenerator

segments = segment_filing_html(999, 'data/gold_standard/Slack_Technologies/filing.html')
segment_dicts = [s.to_dict() for s in segments]
generator = CandidateGenerator()
candidates = generator.generate_for_filing(999, 999, segment_dicts)
billing_cands = [c for c in candidates if c.suggested_metric_id == 'cm_billings']
print(f'cm_billings candidates: {len(billing_cands)} (target: ~5, was 49)')
print(f'Total candidates: {len(candidates)} (was 98)')
EOF

# Run gold standard validation
python scripts/validate_against_gold_standard.py --company "Slack" --mode fresh

# Full test suite
python3 -m pytest tests/unit/ --no-cov -q
```

## Critical Evaluation Phase

**Required for all tasks. Depth: M (Thorough)**

After verification passes but BEFORE committing:
1. Code Quality Review - Are exclusion patterns specific enough?
2. Test Coverage Assessment - Do tests cover the actual FP scenarios observed?
3. Architecture Alignment - Does this follow the YAML-based exclusion pattern?
4. Identify Improvements - Could the exclusions be more precise?
5. **User Approval (REQUIRED)** - STOP and ask user before committing

## Expected Impact

**Before EXT-FP-1**:
- cm_billings candidates for Slack: 49
- Total candidates: 98
- Precision impact: 50% of candidates are FPs from one table segment

**After EXT-FP-1**:
- cm_billings candidates for Slack: ~5 (only legitimate "Calculated Billings" row values)
- Total candidates: ~54
- Precision improvement: ~45% fewer FPs

**Note on target count**: The target is ~5 (not 0) because Slack DOES report "Calculated Billings"
as a legitimate metric. The 5 values (143,390 / 289,013 / 516,972 / 102,080 / 149,637) on the
"Calculated Billings" row should continue to match. The gold standard shows 0 cm_billings because
the metric is deprecated (not because Slack doesn't report billings).

## Reference

- **Issue source**: Extraction Quality Analysis (2026-01-13)
- **Dependencies**: None
- **Related**: HRV-10/HRV-11 (financial statement filtering precedent)
- **Verification date**: 2026-01-14 (pre-execution check confirmed 49 FPs still exist)

---

**Last Updated**: 2026-01-14
**Format Version**: 2.6

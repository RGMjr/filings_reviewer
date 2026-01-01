# WORKER PROMPT: Task EI-2 - Enhance CAC Payback Period Detection

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EI-2
TASK NAME:     Add "payback period on CAC" pattern variant for cm_cac_payback_period
WORKSTREAM:    Extraction Improvements
SOURCE:        Gold standard comparison - Farfetch filing missing CAC payback value
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 15-30 min
TIME ACTUAL:   N/A
RISK LEVEL:    None - Additive pattern change
TASK SIZE:     XS (<30 min)
DEPENDS ON:    None
UNLOCKS:       VAL-1
BLOCKS:        None
PARALLEL WITH: GS-1, GS-2
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add a keyword pattern variant to detect "payback period on CAC" which appears in the Farfetch filing but isn't matched by current patterns.

**Business Rationale**: The gold standard shows a CAC payback period value of 6 months that isn't being detected. Adding this pattern will improve recall for unit economics metrics.

**Current Behavior**:
- Pattern `\bpayback\s+period\b` exists but doesn't match "payback period on CAC"
- Value "6" (months) in Farfetch filing is not generating a candidate

**Desired Behavior**:
- Pattern matches "payback period on CAC" and "payback period for CAC"
- Value "6" generates a candidate for cm_cac_payback_period

## Prerequisites

- None (standalone YAML edit)

## Files to Modify

1. **`config/metric_keywords.yaml`** - Add pattern variant to cm_cac_payback_period (lines 218-222)

## Implementation Requirements

### Core Functionality

1. **Add Pattern Variant**
   - Add: `'\bpayback\s+period\s+(?:on|for)\s+cac\b'`
   - This matches "payback period on CAC" and "payback period for CAC"

2. **Add Specific Patterns** (optional, for confidence bonus)
   - Add `specific_patterns` section with multi-word phrases

### Updated YAML Structure

```yaml
cm_cac_payback_period:
  patterns:
    - '\bcac\s+payback\b'
    - '\bpayback\s+period\b'
    - '\btime\s+to\s+recover\b'
    - '\bpayback\s+period\s+(?:on|for)\s+cac\b'  # NEW
  specific_patterns:
    - 'payback period on CAC'
    - 'CAC payback period'
```

## Test Requirements

### Coverage Target: N/A (YAML-only change)

### Verification Steps

1. Run keyword matching tests to ensure no regressions
2. Regenerate Farfetch candidates
3. Verify CAC payback period value (6) is detected

## Acceptance Criteria

- [ ] Pattern `\bpayback\s+period\s+(?:on|for)\s+cac\b` added to cm_cac_payback_period
- [ ] Optional: specific_patterns added for confidence bonus
- [ ] All existing tests pass
- [ ] Farfetch candidate generation includes CAC payback period value

## Do NOT

- Modify other metrics in the YAML file
- Add required_context (this metric doesn't need context gating)
- Change the metric ID

## Verification Commands

```bash
# Run keyword matching tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py -v -q

# Regenerate Farfetch candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/generate_candidates_for_filing.py --filing-ids 31

# Check for CAC payback in candidates
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -c "
from src.infra.db import DatabaseAdapter
db = DatabaseAdapter('postgresql://dev:dev@localhost:5433/filings_analysis')
results = db.query('''
    SELECT candidate_id, suggested_metric_id, raw_number_text, triggering_keyword
    FROM review_candidates
    WHERE filing_id = 31 AND suggested_metric_id = 'cm_cac_payback_period'
''')
print(f'CAC payback candidates: {len(results)}')
for r in results:
    print(f'  {r}')
"
```

## Expected Impact

**Before EI-2**:
- "payback period on CAC" not matched
- CAC payback value (6 months) missing from candidates

**After EI-2**:
- Pattern matches the variant
- CAC payback value appears in Farfetch candidates

---

**Last Updated**: 2026-01-01
**Format Version**: 2.4

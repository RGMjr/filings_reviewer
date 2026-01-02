# WORKER PROMPT: Task VAL-1 - Validate Extraction Improvements

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       VAL-1
TASK NAME:     Re-run extraction comparison after improvements
WORKSTREAM:    Validation
SOURCE:        Post-improvement validation step
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-60 min
TIME ACTUAL:   N/A
RISK LEVEL:    None - Read-only validation
TASK SIZE:     S (30 min - 1 hr)
DEPENDS ON:    EI-2, GS-1, GS-2
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Re-run the extraction comparison after all improvements are complete to measure final recall/precision.

**Business Rationale**: Validate that the extraction improvements (EI-2) and gold standard updates (GS-1, GS-2) have the expected impact on system performance metrics.

**Baseline Performance**:
| Company | Recall | Precision | Notes |
|---------|--------|-----------|-------|
| Farfetch | 30.8% | 30.8% | Excludes chart values |
| Slack | 83.3% | 13.2% | Low precision due to narrow gold |

## Prerequisites

- EI-2 complete (CAC payback pattern added)
- GS-1 complete (Slack gold standard expanded)
- GS-2 complete (Farfetch gold standard expanded + chart values marked)

## Steps

### 1. Regenerate Candidates

```bash
# Clear existing candidates for Farfetch and Slack
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 -c "
from src.infra.db import DatabaseAdapter
db = DatabaseAdapter('postgresql://dev:dev@localhost:5433/filings_analysis')
db.execute('DELETE FROM review_decisions WHERE candidate_id IN (SELECT candidate_id FROM review_candidates WHERE filing_id IN (31, 35))')
db.execute('DELETE FROM review_candidates WHERE filing_id IN (31, 35)')
print('Cleared candidates for Farfetch (31) and Slack (35)')
"

# Regenerate
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/generate_candidates_for_filing.py --filing-ids 31,35
```

### 2. Run Comparison Script

```bash
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 << 'PYTHON_SCRIPT'
import csv
import re
from collections import defaultdict
from src.infra.db import DatabaseAdapter

db = DatabaseAdapter('postgresql://dev:dev@localhost:5433/filings_analysis')

# Get candidates
candidates = db.query('''
    SELECT
        rc.candidate_id,
        rc.filing_id,
        rc.suggested_metric_id,
        rc.raw_number_text,
        rc.triggering_keyword,
        c.company_name
    FROM review_candidates rc
    JOIN filings f ON rc.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    WHERE rc.filing_id IN (31, 35)
''')

# Parse gold standard (excluding chart values and definition-only)
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    gold_rows = list(reader)

def normalize_value(val):
    if not val:
        return None
    val = str(val).strip()
    if val.lower() in ('chart', ''):
        return None
    val = re.sub(r'[,\s%$]', '', val)
    match = re.search(r'[\d.]+', val)
    return match.group() if match else None

# Build gold standard (exclude chart and definition-only)
gold_by_company = defaultdict(list)
for r in gold_rows:
    company_gold = r.get('Company', '')
    if 'Farfetch' in company_gold:
        company = 'Farfetch'
    elif 'Slack' in company_gold:
        company = 'Slack'
    else:
        continue

    # Skip chart values
    raw = r.get('Raw value', '').strip().lower()
    if raw == 'chart':
        continue

    # Skip definition-only
    is_def = r.get('is_definition_only', '').strip().lower()
    if is_def in ('x', 'true', 'yes', '1'):
        continue

    metric = r.get('Standard Metric Name', '').strip()
    if 'not a customer metric' in metric.lower():
        continue

    norm_val = normalize_value(r.get('Raw value', ''))
    if metric and norm_val:
        gold_by_company[company].append({
            'metric': metric,
            'value': norm_val
        })

print("=" * 70)
print("POST-IMPROVEMENT EXTRACTION COMPARISON")
print("=" * 70)

for company in ['Farfetch', 'Slack']:
    company_cands = [c for c in candidates if company in c['company_name']]
    gold = gold_by_company[company]

    # Build sets
    gold_set = {(g['metric'], g['value']) for g in gold}
    cand_set = {(c['suggested_metric_id'], normalize_value(c['raw_number_text']))
                for c in company_cands if normalize_value(c['raw_number_text'])}

    matches = gold_set & cand_set
    missed = gold_set - cand_set
    extra = cand_set - gold_set

    recall = len(matches) / len(gold_set) * 100 if gold_set else 0
    precision = len(matches) / len(cand_set) * 100 if cand_set else 0

    print(f"\n{company}:")
    print(f"  Gold Standard: {len(gold_set)} values")
    print(f"  Candidates: {len(cand_set)} values")
    print(f"  True Positives: {len(matches)}")
    print(f"  Missed: {len(missed)}")
    print(f"  Extra: {len(extra)}")
    print(f"  Recall: {recall:.1f}%")
    print(f"  Precision: {precision:.1f}%")

print("\n" + "=" * 70)
PYTHON_SCRIPT
```

### 3. Document Results

Create summary with:
- Before/after metrics comparison
- Any remaining gaps identified
- Recommendations for future improvements

## Acceptance Criteria

- [ ] Candidates regenerated for both filings
- [ ] Comparison script runs successfully
- [ ] Farfetch recall improved (was 30.8%)
- [ ] Slack precision improved significantly (was 13.2%)
- [ ] Summary report created

## Expected Outcomes

| Company | Baseline Recall | Expected Recall | Baseline Precision | Expected Precision |
|---------|----------------|-----------------|-------------------|-------------------|
| Farfetch | 30.8% | ≥50% | 30.8% | ≥60% |
| Slack | 83.3% | ≥80% | 13.2% | ≥50% |

---

**Last Updated**: 2026-01-01
**Format Version**: 2.4

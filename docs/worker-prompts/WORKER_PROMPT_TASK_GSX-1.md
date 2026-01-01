# WORKER PROMPT: Task GSX-1 - Expand Slack Gold Standard

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GSX-1
TASK NAME:     Add valid Slack metrics to gold standard CSV
WORKSTREAM:    Gold Standard Expansion
SOURCE:        Gold standard comparison - System extracts valid metrics not in gold
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-60 min
TIME ACTUAL:   N/A
RISK LEVEL:    None - Data file update only
TASK SIZE:     S (30 min - 1 hr)
DEPENDS ON:    None
UNLOCKS:       VAL-1
BLOCKS:        None
PARALLEL WITH: EI-2, GSX-2
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Expand the Slack section of the gold standard CSV to include valid customer metrics that the system correctly extracts but are currently missing from gold.

**Business Rationale**: The system correctly identifies many Slack metrics (Paid Customers, Large Customers >$100K) that aren't in the gold standard, causing artificially low precision scores (13.2%). Adding these will give an accurate picture of system performance.

**Current Gold Standard (Slack)**:
- cm_daily_active_users: 2 values
- cm_net_revenue_retention: 10 values
- Total: 12 values

**Metrics Being Correctly Extracted (Not in Gold)**:
- cm_customers_period_end: ~10 values (Paid Customers)
- cm_large_customers_period_end: ~8 values (>$100K customers)

## Prerequisites

- None (data file update only)
- Access to Slack S-1 filing for verification

## Files to Modify

1. **`data/gold_standard/golden_set_251218.csv`** - Add Slack metric rows

## Implementation Requirements

### Metrics to Add

#### 1. cm_customers_period_end (Paid Customers)
| Raw Value | Scaled Value | Period | Context |
|-----------|--------------|--------|---------|
| 37,000 | 37,000 | 31-Jan-17 | Paid Customers table |
| 42,000 | 42,000 | 30-Apr-17 | Paid Customers table |
| 47,000 | 47,000 | 31-Jan-18 | Paid Customers table |
| 52,000 | 52,000 | 30-Apr-18 | Paid Customers table |
| 59,000 | 59,000 | 31-Jan-18 | Paid Customers table |
| 67,000 | 67,000 | 30-Apr-18 | Paid Customers table |
| 88,000 | 88,000 | 31-Jan-19 | Paid Customers (prose) |
| 95,000 | 95,000 | 30-Apr-19 | Paid Customers (prose) |
| 500,000 | 500,000 | 31-Jan-19 | Free subscription plan |
| 600,000 | 600,000 | 31-Jan-19 | Organizations with 3+ users |

#### 2. cm_large_customers_period_end (>$100K ARR)
| Raw Value | Scaled Value | Period | Context |
|-----------|--------------|--------|---------|
| 135 | 135 | 31-Jan-17 | Paid Customers >$100K table |
| 164 | 164 | 30-Apr-17 | Paid Customers >$100K table |
| 209 | 209 | 31-Jan-18 | Paid Customers >$100K table |
| 298 | 298 | 30-Apr-18 | Paid Customers >$100K table |
| 351 | 351 | 31-Jan-18 | Paid Customers >$100K table |
| 575 | 575 | 31-Jan-19 | Paid Customers >$100K (prose) |
| 645 | 645 | 30-Apr-19 | Paid Customers >$100K (prose) |

### CSV Format

Follow existing CSV structure:
```csv
Document URL,Company,Standard Metric Name,New standard metric?,Name in the text,Raw value,Scaled value,Scale/unit,Period,Definition,Quote/context,segment_type,is_definition_only,value_context,detection_difficulty,period_start,period_end
```

## Acceptance Criteria

- [ ] cm_customers_period_end values added to Slack section (~10 rows)
- [ ] cm_large_customers_period_end values added to Slack section (~7 rows)
- [ ] CSV formatting matches existing structure
- [ ] No duplicate entries
- [ ] File loads without errors

## Do NOT

- Modify Farfetch entries (handled by GSX-2)
- Change existing Slack entries (DAU, NRR)
- Add metrics that haven't been verified in the filing

## Verification Commands

```bash
# Check CSV loads correctly
python3 -c "
import csv
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    slack = [r for r in rows if 'Slack' in r.get('Company', '')]
    print(f'Total Slack rows: {len(slack)}')
    metrics = {}
    for r in slack:
        m = r.get('Standard Metric Name', '')
        if m not in metrics:
            metrics[m] = 0
        metrics[m] += 1
    for m, c in sorted(metrics.items()):
        print(f'  {m}: {c}')
"
```

## Expected Impact

**Before GSX-1**:
- Slack gold standard: 12 values
- Precision appears low (13.2%) due to missing valid metrics

**After GSX-1**:
- Slack gold standard: ~29 values
- Precision will reflect actual system accuracy

---

**Last Updated**: 2026-01-01
**Format Version**: 2.4

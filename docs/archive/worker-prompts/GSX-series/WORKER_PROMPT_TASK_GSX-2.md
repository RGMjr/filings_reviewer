# WORKER PROMPT: Task GSX-2 - Expand Farfetch Gold Standard

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GSX-2
TASK NAME:     Add valid Farfetch metrics and mark chart values in gold standard
WORKSTREAM:    Gold Standard Expansion
SOURCE:        Gold standard comparison - System extracts valid metrics not in gold
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 15-30 min
TIME ACTUAL:   N/A
RISK LEVEL:    None - Data file update only
TASK SIZE:     XS (<30 min)
DEPENDS ON:    None
UNLOCKS:       VAL-1
BLOCKS:        None
PARALLEL WITH: EI-2, GSX-1
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

1. Add valid customer metrics (Number of Orders, Take Rate) to Farfetch gold standard
2. Mark gross margin by cohort values as "chart" (not extractable from text)

**Business Rationale**: The system correctly extracts Number of Orders and Take Rate metrics that aren't in gold. Additionally, the 6 gross margin values appear in chart images and shouldn't count against text extraction recall.

**Current Gold Standard (Farfetch)**:
- cm_active_customers_total: 7 values
- cm_cac_payback_period: 1 value
- cm_gross_margin_by_cohort: 6 values (IN CHARTS - not extractable)
- Total: 14 values

## Prerequisites

- None (data file update only)

## Files to Modify

1. **`data/gold_standard/golden_set_251218.csv`** - Add/update Farfetch rows

## Implementation Requirements

### 1. Metrics to Add (CONFIRMED VALID)

#### cm_purchase_transactions_overall (Number of Orders)
| Raw Value | Scaled Value | Period | Context |
|-----------|--------------|--------|---------|
| 800,500 | 800,500 | FY2016 | Number of Orders |
| 853,195 | 853,195 | FY2017 | Number of Orders |
| 1,305,297 | 1,305,297 | FY2018 | Number of Orders |
| ~1.3 million | 1,300,000 | FY2018 | Number of Orders (prose) |
| ~1.9 million | 1,900,000 | FY2019 | Number of Orders (prose) |

#### cm_take_rate (Take Rate)
| Raw Value | Scaled Value | Period | Context |
|-----------|--------------|--------|---------|
| 30.0% | 30.0 | FY2016 | Take Rate |
| 31.3% | 31.3 | FY2017 | Take Rate |
| 32.9% | 32.9 | FY2018 | Take Rate |

### 2. Mark Chart Values

Update the 6 `cm_gross_margin_by_cohort` entries:
- Set `Raw value` column to "chart" (or add note in value_context)
- This indicates values are in images, not extractable text

**Gross Margin Values in Charts**:
- 23%, 26%, 31%, 46%, 54% (Order Contribution Margin by cohort)
- These appear in cohort chart images in the filing

### CSV Format

Follow existing CSV structure. Example:
```csv
https://www.sec.gov/Archives/edgar/data/1740915/000119312519063862/d642768df1a.htm,Farfetch Ltd,cm_purchase_transactions_overall,,Number of Orders,1305297,1305297,orders,FY2018,,Quote here,,,,,,
```

## Acceptance Criteria

- [ ] cm_purchase_transactions_overall values added (~5 rows)
- [ ] cm_take_rate values added (3 rows)
- [ ] cm_gross_margin_by_cohort entries marked as "chart" values
- [ ] CSV formatting matches existing structure
- [ ] File loads without errors

## Do NOT

- Modify Slack entries (handled by GSX-1)
- Remove gross margin entries entirely (just mark as chart)
- Add metrics that haven't been verified

## Verification Commands

```bash
# Check CSV loads correctly
python3 -c "
import csv
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    farfetch = [r for r in rows if 'Farfetch' in r.get('Company', '')]
    print(f'Total Farfetch rows: {len(farfetch)}')
    metrics = {}
    for r in farfetch:
        m = r.get('Standard Metric Name', '')
        if m not in metrics:
            metrics[m] = 0
        metrics[m] += 1
    for m, c in sorted(metrics.items()):
        print(f'  {m}: {c}')

    # Check chart values
    chart_vals = [r for r in farfetch if 'chart' in str(r.get('Raw value', '')).lower()]
    print(f'\\nChart values: {len(chart_vals)}')
"
```

## Expected Impact

**Before GSX-2**:
- Farfetch gold standard: 14 values (6 are in charts)
- Precision: 30.8%

**After GSX-2**:
- Farfetch gold standard: ~22 values (6 marked as chart)
- Chart values excluded from text extraction recall calculation
- Precision reflects actual extractable metrics

---

**Last Updated**: 2026-01-01
**Format Version**: 2.4

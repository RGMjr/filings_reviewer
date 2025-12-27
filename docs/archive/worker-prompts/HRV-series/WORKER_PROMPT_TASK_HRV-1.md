# WORKER PROMPT: Task HRV-1 - Improve Gold Standard CSV Schema

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-1
TASK NAME:     Add columns to gold standard CSV for better machine parseability
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (schema design 20 min, migration script 30 min, validation 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Additive columns only, existing data preserved
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       HRV-3, HRV-4, HRV-5 (new columns improve review workflow)
BLOCKS:        None
PARALLEL WITH: HRV-2
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add 6 new columns to the gold standard CSV to enable machine-parseable validation and better classification of metrics during human review.

**Business Rationale**: The current CSV schema lacks structured fields needed for automated precision/recall calculation. Adding segment_type, value_context, and split period fields enables the validation scripts (HRV-2) to compare system output against gold standard programmatically.

**Current Behavior**: CSV has 11 columns with free-form text for Period field. Cannot programmatically match against system-detected segments.

**Desired Behavior**: CSV has 17 columns with machine-parseable fields. Validation scripts can match by segment_type, compare period ranges, and categorize detection difficulty.

## Prerequisites

- None (standalone)
- Read `data/gold_standard/golden_set_251218.csv` to understand current schema

## Files to Modify

1. **`data/gold_standard/golden_set_251218.csv`** - Add 6 new columns to header and existing rows

## Files to Create

1. **`scripts/migrate_gold_standard_schema.py`** - One-time migration script (can delete after use)

## Files to Read (Context Only)

- `docs/HUMAN_REVIEW_VALIDATION_PLAN.md` - Full schema specification

## Implementation Requirements

### Core Functionality

1. **New Columns to Add**
   | Column | Type | Values | Purpose |
   |--------|------|--------|---------|
   | `segment_type` | enum | paragraph/table/list_item/empty | Match against system detection |
   | `is_definition_only` | boolean | TRUE/FALSE/empty | Filter definitional mentions |
   | `value_context` | enum | inline/table_cell/chart/empty | Where value appears |
   | `detection_difficulty` | enum | easy/medium/hard/empty | Prioritize FN investigation |
   | `period_start` | date | YYYY-MM-DD or empty | Machine-parseable period start |
   | `period_end` | date | YYYY-MM-DD or empty | Machine-parseable period end |

2. **Migration Script**
   - Read existing CSV with csv.DictReader
   - Add 6 new columns with empty values
   - Preserve all existing 108 rows exactly
   - Write output with csv.DictWriter
   - Use UTF-8-SIG encoding (handles BOM)

3. **Preserve Existing Data**
   - All 11 existing columns unchanged
   - All 108 existing rows unchanged
   - Multi-line quoted content preserved correctly

### Error Handling

- **CSV Parse Errors**: Log specific row number and content causing issue
- **Encoding Issues**: Use UTF-8-SIG to handle Excel compatibility
- **Empty Values**: New columns default to empty string, not NULL

## Test Requirements

### No Automated Tests Required

This is a data migration task. Validation is manual:

1. **Row Count Validation**
   ```python
   import csv
   with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
       reader = csv.DictReader(f)
       rows = list(reader)
       assert len(rows) == 108, f"Expected 108 rows, got {len(rows)}"
   ```

2. **Column Count Validation**
   ```python
   assert len(reader.fieldnames) == 17, f"Expected 17 columns, got {len(reader.fieldnames)}"
   ```

3. **New Column Presence**
   ```python
   new_cols = ['segment_type', 'is_definition_only', 'value_context',
               'detection_difficulty', 'period_start', 'period_end']
   for col in new_cols:
       assert col in reader.fieldnames, f"Missing column: {col}"
   ```

## Acceptance Criteria

- [ ] CSV has 17 columns (11 original + 6 new)
- [ ] All 108 existing rows preserved (no data loss)
- [ ] New columns present: segment_type, is_definition_only, value_context, detection_difficulty, period_start, period_end
- [ ] CSV parseable with `csv.DictReader(open(file, encoding='utf-8-sig'))`
- [ ] Multi-line quoted content still works (test row with long Quote/context)
- [ ] Migration script created and documented

## Do NOT

- Modify any existing column values
- Delete any existing rows
- Change column order of existing columns
- Add column documentation inside CSV (keep header row only)

## Verification Commands

```bash
# Verify CSV row count
python3 -c "
import csv
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    print(f'Rows: {len(rows)}')
    print(f'Columns: {len(reader.fieldnames)}')
    print(f'Column names: {reader.fieldnames}')
    assert len(rows) == 108
    assert len(reader.fieldnames) == 17
    print('✅ Schema migration validated')
"

# Verify specific new columns
python3 -c "
import csv
new_cols = ['segment_type', 'is_definition_only', 'value_context',
            'detection_difficulty', 'period_start', 'period_end']
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for col in new_cols:
        assert col in reader.fieldnames, f'Missing: {col}'
    print('✅ All new columns present')
"
```

## Expected Impact

**Before HRV-1**:
- 11 columns, no machine-parseable segment info
- Period field is free-form text (e.g., "FY 2019", "Q3 2020")
- Cannot programmatically validate system output

**After HRV-1**:
- 17 columns with structured data fields
- Validation scripts can match by segment_type
- Detection difficulty enables FN prioritization

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: None
- **Related**: HRV-2 (will use updated schema)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4

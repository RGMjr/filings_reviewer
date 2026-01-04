# WORKER PROMPT: Task HRV-9 - Remove Growth Metric Detection

```markdown
===============================================================================
TASK ID:       HRV-9
TASK NAME:     Remove growth metric detection from the system
WORKSTREAM:    Human Review Validation - System Improvements (Phase 4c)
SOURCE:        User decision 2026-01-02 (growth metrics provide no value)
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-1.5 hours (research 15m, edits 30m, verification 30m, docs 15m)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Removing unused patterns, no architectural changes
TASK SIZE:     S (30min-2hr)
DEPENDS ON:    HRV-4 (Farfetch validation analysis complete)
UNLOCKS:       HRV-12 (Industry-specific keyword weighting)
BLOCKS:        HRV-12 (must complete HRV-9 first)
PARALLEL WITH: None
===============================================================================
```

## Objective

Remove all growth metric detection from the system to eliminate redundancy and confusion.

**Business Rationale**: Growth metrics (e.g., "57% Active Consumers growth") always appear alongside the base metrics they describe (e.g., "1.1M Active Consumers"). Detecting growth separately adds no value because:
1. Growth percentages are relative values requiring the base metric for context
2. Growth can be calculated from period-over-period base metric values
3. Duplicate detection causes confusion in review candidates

**Current Behavior**: System detects growth metrics via:
- `cm_purchase_transactions_overall_growth` metric in YAML and database
- `\bcustomer\s+growth\b` and `\bconsumer\s+growth\b` patterns in `cm_new_customers_acquired`

**Desired Behavior**: System does NOT detect growth metrics. Growth-related text is ignored.

## Prerequisites

- [x] HRV-4: Farfetch validation complete
- [x] User decision: Growth metrics provide no value (2026-01-02)
- [x] Gold standard already marks "Active Consumers growth" as "Not a customer metric"

## Files to Modify

1. **`config/metric_keywords.yaml`** - Remove growth metric and patterns
2. **`sql/04_seed_metrics_taxonomy.sql`** - Remove or comment out growth metric INSERT
3. **`data/gold_standard/golden_set_251218.csv`** - Update 2 rows to mark as "Not a customer metric"
4. **`docs/PROJECT_TASK_INVENTORY.md`** - Update HRV-9 description

## Files to Read (Context Only)

- `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` - Contains original recommendation (now superseded)

## Implementation Requirements

### Phase 1: Update Gold Standard CSV (MUST BE FIRST)

Update the CSV **before** modifying YAML to ensure gold standard validation has correct expectations.

**File**: `data/gold_standard/golden_set_251218.csv`

**Rows to update** (match by document URL + "Number of Orders growth" in column 5):

| Match Criteria | Column 3 (Standard Metric Name) | Column 4 (New standard metric?) |
|----------------|--------------------------------|--------------------------------|
| Farfetch + "Number of Orders growth" + 57% | Change to blank | Change to `Not a customer metric` |
| Farfetch + "Number of Orders growth" + 49% | Change to blank | Change to `Not a customer metric` |

**Method**: Use targeted search/replace or Python script:
```python
# Example approach - find rows where column 5 contains "Number of Orders growth"
# Change column 3 to empty, column 4 to "Not a customer metric"
```

### Phase 2: Remove from YAML

**File**: `config/metric_keywords.yaml`

1. **Delete the entire `cm_purchase_transactions_overall_growth` block**
   - Find: `cm_purchase_transactions_overall_growth:`
   - Delete from that line through all its `patterns:` and `specific_patterns:` entries
   - Keep the comment section header `# Growth Metrics` but update it

2. **Remove growth patterns from `cm_new_customers_acquired`**
   - Find and delete: `- '\bcustomer\s+growth\b'`
   - Find and delete: `- '\bconsumer\s+growth\b'`

3. **Update the Growth Metrics comment section** to explain the decision:
   ```yaml
   # =============================================================================
   # Growth Metrics - INTENTIONALLY NOT DETECTED
   # =============================================================================
   # Decision (2026-01-02): Growth metrics are not tracked separately because:
   # 1. They always appear alongside base metrics (e.g., "1.1M customers, up 57%")
   # 2. Growth can be calculated from period-over-period base metric values
   # 3. Detecting both creates duplicate/confusing review candidates
   # =============================================================================
   ```

### Phase 3: Update SQL Seed File

**File**: `sql/04_seed_metrics_taxonomy.sql`

Comment out or delete the `cm_purchase_transactions_overall_growth` INSERT statement:
```sql
-- REMOVED (2026-01-02): Growth metrics not tracked separately
-- INSERT INTO metrics (metric_id, display_name, ...)
-- VALUES ('cm_purchase_transactions_overall_growth', ...);
```

### Phase 4: Update Documentation

**File**: `docs/PROJECT_TASK_INVENTORY.md`

Find all references to HRV-9 and update:
- Change "Growth rate detection patterns" → "Remove growth metric detection"
- Update status descriptions in Phase 4c section

### Phase 5: Verification

Run in this order:

```bash
# 1. Verify YAML changes
grep -n "cm_purchase_transactions_overall_growth" config/metric_keywords.yaml
# Expected: No matches

grep -n "customer.*growth\|consumer.*growth" config/metric_keywords.yaml
# Expected: Only comment lines (starting with #)

# 2. Verify SQL changes
grep -n "cm_purchase_transactions_overall_growth" sql/04_seed_metrics_taxonomy.sql
# Expected: Only commented lines

# 3. Verify CSV changes
grep "Number of Orders growth" data/gold_standard/golden_set_251218.csv | head -2
# Expected: Column 4 should show "Not a customer metric"

# 4. Run tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q

# 5. Gold standard validation (CSV was updated first, so baseline is correct)
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## Error Handling

- **If tests fail**: Check if any test explicitly references the removed metric
- **If gold standard validation regresses**: Verify CSV was updated before YAML
- **Rollback**: `git checkout config/metric_keywords.yaml sql/04_seed_metrics_taxonomy.sql`

## Acceptance Criteria

- [ ] `cm_purchase_transactions_overall_growth` metric block removed from YAML
- [ ] `\bcustomer\s+growth\b` pattern removed from `cm_new_customers_acquired`
- [ ] `\bconsumer\s+growth\b` pattern removed from `cm_new_customers_acquired`
- [ ] SQL seed file has growth metric INSERT commented out or removed
- [ ] Gold standard CSV rows for "Number of Orders growth" marked "Not a customer metric"
- [ ] `docs/PROJECT_TASK_INVENTORY.md` HRV-9 description updated
- [ ] All existing tests pass
- [ ] Gold standard validation passes (no regression)

## Do NOT

- Add any new growth-related patterns
- Modify `src/review/keyword_matching.py` (no code changes needed)
- Modify `src/extraction/metric_classifier.py` (no code changes needed)
- Delete the Growth Metrics comment section (update it to explain the decision)
- Update `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` (keep as historical record)

## Verification Commands

```bash
# Complete verification sequence
echo "=== Phase 1: Check YAML ==="
grep -c "cm_purchase_transactions_overall_growth" config/metric_keywords.yaml && echo "FAIL" || echo "PASS"

echo "=== Phase 2: Check growth patterns ==="
grep "customer.s.growth\|consumer.s.growth" config/metric_keywords.yaml | grep -v "^#" && echo "FAIL" || echo "PASS"

echo "=== Phase 3: Check SQL ==="
grep "cm_purchase_transactions_overall_growth" sql/04_seed_metrics_taxonomy.sql | grep -v "^--" && echo "FAIL" || echo "PASS"

echo "=== Phase 4: Check CSV ==="
grep "Number of Orders growth" data/gold_standard/golden_set_251218.csv | grep -q "Not a customer metric" && echo "PASS" || echo "FAIL"

echo "=== Phase 5: Run tests ==="
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q

echo "=== Phase 6: Gold standard validation ==="
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## Critical Evaluation Phase

**Required. Depth: Standard (S-sized task).**

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] YAML is valid (no syntax errors)
- [ ] No orphaned references to removed metric in modified files

### 2. Test Coverage Assessment
- [ ] No tests broke from removal
- [ ] Searched for tests referencing the removed metric

### 3. Architecture Alignment
- [ ] Removal is clean
- [ ] Decision documented in YAML comments

### 4. Identify Improvements
Document any related cleanup discovered during implementation.

### 5. User Approval (REQUIRED)
**STOP and ask the user** before committing.

## Expected Impact

**Before HRV-9**:
- System detects "Number of Orders growth 57%" as `cm_purchase_transactions_overall_growth`
- Creates duplicate/confusing candidates alongside base metric

**After HRV-9**:
- Growth mentions ignored
- Only base metrics detected
- Cleaner candidate list for reviewers
- Gold standard validation unaffected (growth already marked "Not a customer metric")

## Reference

- **Decision source**: User decision 2026-01-02 - growth metrics don't add value
- **Prior analysis**: HRV-6 originally recommended adding growth patterns (superseded; kept as historical record)
- **Related**: HRV-12 (industry weighting - unblocked after this task)

## Files With References (for awareness)

These files reference growth metrics but do NOT need modification (historical records):
- `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` - Original recommendation
- `docs/archive/2025-12-goldmine-analysis/GI-1_cohort_pattern_gaps.md`
- `docs/archive/2025-12-goldmine-analysis/GI-8_validation_results.md`

---

**Last Updated**: 2026-01-02
**Format Version**: 2.6

# Worker Prompt: MET-11 - Final MET Workstream Validation and Cleanup

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-11 |
| Task Name | Final MET Workstream Validation and Cleanup |
| Size | XS (30 minutes) |
| Priority | Low |
| Dependencies | MET-1, MET-7, MET-8 (all complete) |
| Blocking | None |

## Objective

Close out the MET workstream by:
1. Verifying the live database matches SQL definitions
2. Running gold standard validation to confirm no regressions
3. Committing the pending false_positive_filter.py fix
4. Updating inventory to reflect actual completion status

## Background

**Critical Evaluation (2026-01-07)**: The original MET-11 scope was obsolete. The code changes it claimed to "validate and commit" were already completed:

| Original Claim | Actual Status |
|----------------|---------------|
| Dropdown ordering uncommitted | ✅ Committed in MET-8 (b9c9ecd) |
| Pattern move uncommitted | ✅ Committed in MET-1/MET-7 |
| New metric uncommitted | ✅ Already in YAML, SQL, value_extractor.py |
| Deprecations uncommitted | ✅ Already in SQL with 'deprecated' status |

**Actual pending work**:
- `src/review/false_positive_filter.py`: Adds 4 metrics to COUNT_ONLY_METRICS (cm_customers_period_end, cm_active_customers_total, cm_large_customers_period_end, cm_new_customers_acquired)
- Inventory cleanup: MET-3/4/5/6 should be marked COMPLETE

## Requirements

### R1: Verify Live Database State

```bash
# Connect to live database
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" psql -c "
SELECT metric_id, status
FROM metrics
WHERE metric_id IN (
    'cm_gmv', 'cm_bookings', 'cm_billings', 'cm_acv', 'cm_tcv',
    'cm_ltv_to_cac_ratio_by_cohort', 'cm_customers_period_end'
)
ORDER BY metric_id;
"
```

**Expected**:
- GMV, Bookings, Billings, ACV, TCV → 'deprecated'
- cm_ltv_to_cac_ratio_by_cohort → 'active'
- cm_customers_period_end → 'active'

**If mismatch**: Re-run the seed file or apply targeted UPDATE statements.

### R2: Run Gold Standard Validation

```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

All tests must pass. This confirms MET-1/MET-7/MET-8 changes didn't cause regressions.

### R3: Commit Pending Fix

```bash
# Verify what's pending
git diff src/review/false_positive_filter.py

# Stage and commit
git add src/review/false_positive_filter.py
git commit -m "$(cat <<'EOF'
fix(MET-11): Add missing customer metrics to COUNT_ONLY_METRICS

Add 4 metrics that were missing from the percentage filter set:
- cm_customers_period_end
- cm_active_customers_total
- cm_large_customers_period_end
- cm_new_customers_acquired

These metrics should reject percentage values (e.g., "50%") as they
represent count-based metrics, not rates.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

### R4: Update Inventory

Update `docs/PROJECT_TASK_INVENTORY.md`:

1. Mark MET-3, MET-4, MET-5, MET-6 as ✅ COMPLETE with notes:
   - MET-3: "Completed via MET-8 (b9c9ecd)"
   - MET-4: "Completed via MET-1/MET-7"
   - MET-5: "Already implemented - verified present in YAML, SQL, value_extractor.py"
   - MET-6: "Already implemented - all 5 metrics deprecated in SQL"

2. Mark MET-11 as ✅ COMPLETE

3. Update MET workstream summary: "10/10 complete"

### R5: Archive Worker Prompts

```bash
# Move all MET worker prompts to completed archive
git mv docs/worker-prompts/WORKER_PROMPT_TASK_MET-*.md docs/archive/worker-prompts-completed/
```

## Verification Commands

```bash
# 1. Database state
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" psql -c "SELECT metric_id, status FROM metrics WHERE status = 'deprecated' ORDER BY metric_id;"

# 2. Gold standard
pytest -m gold_standard --gold-standard-mode=fresh -v

# 3. Working tree clean
git status
```

## Deliverables

1. **Database verified**: Live DB matches SQL definitions
2. **Gold standard passed**: No regressions from MET work
3. **Fix committed**: false_positive_filter.py change committed
4. **Inventory updated**: MET-3/4/5/6/11 marked complete
5. **Prompts archived**: All MET worker prompts in completed archive

## Out of Scope

- Pushing to remote (user decision)
- Re-running candidate generation (separate task if needed)

## Completion Checklist

- [ ] Verify live database has correct metric statuses
- [ ] Run gold standard validation (all tests pass)
- [ ] Commit false_positive_filter.py fix
- [ ] Update PROJECT_TASK_INVENTORY.md (MET-3/4/5/6/11 → COMPLETE)
- [ ] Archive MET worker prompts
- [ ] Final git status shows clean working tree

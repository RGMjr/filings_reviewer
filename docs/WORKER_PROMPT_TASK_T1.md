## WORKER PROMPT for Task T1

```markdown
# WORKER PROMPT: Task T1 - Add Aggregate Metrics to Taxonomy

## Task ID
T1

## Objective
Update the metrics taxonomy seed file to include three new aggregate metrics: `cm_bookings`, `cm_billings`, and `cm_deferred_revenue`.

## Context
The current taxonomy (`sql/04_seed_metrics_taxonomy.sql`) defines canonical customer metrics. Analysis in `docs/archive/analysis/METRICS_IMPROVEMENT_ANALYSIS.md` identified that common aggregate metrics are currently missed by the extraction pipeline. Adding these to the taxonomy is a prerequisite for adding detection patterns in T5-T6.

## Files to Modify
- `sql/04_seed_metrics_taxonomy.sql` (PRIMARY)

## Files to Read for Context
- `sql/04_seed_metrics_taxonomy.sql` - Understand existing metric structure
- `docs/architecture/data-model.md` - Understand schema constraints
- `docs/development/metrics-taxonomy.md` - Understand naming conventions and categories

## Deliverables

### 1. Add Three New Metrics to Seed File

Each metric needs an INSERT statement following the existing pattern. Use these specifications:

**cm_bookings:**
- `metric_id`: `cm_bookings`
- `metric_name`: `Bookings`
- `category`: `revenue_predictability` (or appropriate existing category)
- `description`: `Total value of customer contracts signed in a period, representing committed future revenue`
- `unit_type`: `currency`
- `keywords`: `bookings, new bookings, total bookings, gross bookings`

**cm_billings:**
- `metric_id`: `cm_billings`
- `metric_name`: `Billings`
- `category`: `revenue_predictability`
- `description`: `Total amounts invoiced to customers in a period, typically revenue plus change in deferred revenue`
- `unit_type`: `currency`
- `keywords`: `billings, total billings, calculated billings`

**cm_deferred_revenue:**
- `metric_id`: `cm_deferred_revenue`
- `metric_name`: `Deferred Revenue`
- `category`: `revenue_predictability`
- `description`: `Payments received from customers for services not yet delivered, representing future revenue obligation`
- `unit_type`: `currency`
- `keywords`: `deferred revenue, unearned revenue, contract liabilities`

### 2. Verify Idempotency
The seed file uses `INSERT ... ON CONFLICT` pattern. Ensure new entries follow the same pattern to allow safe re-runs.

### 3. Validate SQL Syntax
Run the SQL file against the test database to verify no syntax errors:
```bash
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis_test -f sql/04_seed_metrics_taxonomy.sql
```

## Constraints
- Do NOT modify any Python code
- Do NOT modify database schema (only seed data)
- Do NOT add new categories unless absolutely necessary - prefer existing categories
- Follow exact naming convention: `cm_` prefix for metric_id

## Success Criteria
1. Three new metrics added to `sql/04_seed_metrics_taxonomy.sql`
2. SQL file executes without errors
3. Metrics queryable from database after execution:
   ```sql
   SELECT metric_id, metric_name FROM metrics WHERE metric_id IN ('cm_bookings', 'cm_billings', 'cm_deferred_revenue');
   ```

## Estimated Effort
30 minutes

## Post-Completion
After completing T1, T2-T4 can proceed (more taxonomy additions), and T5-T7 will be unblocked (code patterns for these metrics).
```
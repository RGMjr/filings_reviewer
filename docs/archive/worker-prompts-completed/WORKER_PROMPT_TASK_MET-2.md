# Worker Prompt: MET-2 - Metric Lifecycle Process Documentation

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-2 |
| Task Name | Metric Lifecycle Process Documentation |
| Size | S (30 min - 2 hours) |
| Priority | High |
| Dependencies | None |
| Blocking | MET-5, MET-6 |

## Objective

Create comprehensive documentation for the metric lifecycle process, covering:
1. How to add a new metric to the system
2. How to deprecate an existing metric
3. How to remove a metric entirely (if needed)

This documentation will be the authoritative guide for all future metric changes.

## Background

Currently, there is no documented process for adding or removing metrics from the system. Metrics are defined in multiple locations:

| Location | Purpose |
|----------|---------|
| `config/metric_keywords.yaml` | Authoritative source - patterns, exclusions, aliases |
| `sql/04_seed_metrics_taxonomy.sql` | Database seed - display names, classes, status |
| `src/extraction/value_extractor.py` | Python mapping - name variants to canonical IDs |
| `docs/development/metrics-taxonomy.md` | Documentation - business definitions |
| `src/web/routes/review.py` | UI ordering - `METRIC_DISPLAY_ORDER` dict |

Without a documented process, changes risk being incomplete (missing some locations) or inconsistent.

## Requirements

### R1: Create Metric Lifecycle Process Document

Create `docs/development/metric-lifecycle-process.md` with the following sections:

#### Section 1: Overview
- Purpose of the document
- Metric ID naming conventions (`cm_` prefix)
- Reference to authoritative source (YAML)

#### Section 2: Adding a New Metric

Step-by-step checklist with file paths and code examples:

1. **Define in YAML** (`config/metric_keywords.yaml`)
   - Choose metric ID following naming convention
   - Add patterns (regex, case-insensitive)
   - Add exclusions if needed
   - Add specific_patterns for confidence bonus
   - Add required_context if metric needs context-gating
   - Add aliases if metric has equivalent IDs

   Example:
   ```yaml
   cm_new_metric_name:
     patterns:
       - '\bnew\s+metric\s+pattern\b'
     exclusions:
       - '\bexcluded\s+phrase\b'
     specific_patterns:
       - 'new\s+metric\s+pattern'
   ```

2. **Add to Database Seed** (`sql/04_seed_metrics_taxonomy.sql`)
   - INSERT statement with all required fields
   - metric_id, display_name, metric_class, description, primary_concept, status, version

   Example:
   ```sql
   INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
   VALUES (
       'cm_new_metric_name',
       'New Metric Display Name',
       'extended',
       'Description of the metric.',
       'primary_concept',
       'active',
       1
   );
   ```

3. **Add to METRIC_NAME_MAPPING** (`src/extraction/value_extractor.py`)
   - Add all name variants that should map to this metric
   - Example: `"arpu": "cm_revenue_per_customer"`

4. **Add to Dropdown Ordering** (`src/web/routes/review.py`)
   - Add to `METRIC_DISPLAY_ORDER` dict with appropriate sort order within category
   - Use correct category range (see Section 6)

   Example:
   ```python
   METRIC_DISPLAY_ORDER: dict[str, int] = {
       # ... existing entries ...
       "cm_new_metric_name": 28,  # Revenue category (21-30)
   }
   ```

5. **Update Documentation** (`docs/development/metrics-taxonomy.md`)
   - Add metric definition, class, business rules

6. **Run Gold Standard Validation**
   ```bash
   pytest -m gold_standard --gold-standard-mode=fresh
   ```
   - Ensure no regressions
   - If intentional changes, update baseline

7. **Verify in UI**
   - Start Flask app
   - Confirm metric appears in dropdown at correct position

#### Section 3: Deprecating a Metric

Step-by-step checklist (preserves historical data):

1. **Update Database Status** (`sql/04_seed_metrics_taxonomy.sql`)
   - Change `status` from `'active'` to `'deprecated'`
   - Add comment explaining deprecation reason and date

   Example:
   ```sql
   -- cm_old_metric (DEPRECATED 2026-01-07: Reason for deprecation)
   INSERT INTO metrics (..., status, ...)
   VALUES (..., 'deprecated', ...);
   ```

2. **Keep in YAML** (`config/metric_keywords.yaml`)
   - DO NOT remove - needed for historical data interpretation
   - Add comment marking as deprecated

3. **Keep in METRIC_NAME_MAPPING** (`src/extraction/value_extractor.py`)
   - DO NOT remove - needed for validation of existing data

4. **Remove from Dropdown Ordering** (`src/web/routes/review.py`)
   - Remove from `METRIC_DISPLAY_ORDER` dict
   - Deprecated metrics won't appear in UI

5. **Update Documentation** (`docs/development/metrics-taxonomy.md`)
   - Mark as deprecated with date and reason

6. **Run Tests**
   - `pytest tests/unit/web/ -v`
   - Update any test fixtures that expect deprecated metric in dropdown

#### Section 4: Removing a Metric Entirely

**WARNING**: Only do this if metric was never used in production.

Step-by-step checklist:

1. **Check for Existing Data**
   ```sql
   SELECT COUNT(*) FROM metric_values WHERE metric_id = 'cm_xxx';
   SELECT COUNT(*) FROM review_candidates WHERE suggested_metric_id = 'cm_xxx';
   SELECT COUNT(*) FROM review_decisions WHERE assigned_metric_id = 'cm_xxx';
   ```
   - If count > 0, DEPRECATE instead of removing

2. **Remove from all locations** (reverse order of adding):
   - Remove from `src/web/routes/review.py` dropdown ordering
   - Remove from `src/extraction/value_extractor.py` mapping
   - Remove INSERT from `sql/04_seed_metrics_taxonomy.sql`
   - Remove from `config/metric_keywords.yaml`
   - Remove from `docs/development/metrics-taxonomy.md`

3. **Update test fixtures** that reference the metric

4. **Run full test suite**
   ```bash
   pytest -v
   ```

#### Section 5: Metric ID Naming Conventions

- All metric IDs start with `cm_` (customer metric)
- Use snake_case
- Be descriptive but concise
- Examples:
  - `cm_customers_period_end` (not `cm_cust_pe`)
  - `cm_net_revenue_retention` (not `cm_nrr`)
  - `cm_ltv_to_cac_ratio_by_cohort` (cohort variant of base metric)

#### Section 6: Metric Categories for Dropdown Ordering

Define the 5 semantic categories and their sort order ranges:

| Category | Sort Range | Description |
|----------|------------|-------------|
| Customer Count Metrics | 1-10 | Headcount/user counts |
| Transaction & Purchase Behavior | 11-20 | Orders, frequency, AOV |
| Revenue Metrics | 21-30 | ARR, MRR, ARPU, revenue by cohort |
| Retention, Churn & Attrition | 31-40 | NRR, GRR, churn, retention |
| Unit Economics & CAC | 41-50 | LTV, CAC, payback |

### R2: Update CLAUDE.md

Add reference to new documentation in CLAUDE.md under relevant section:

```markdown
## Metric Lifecycle

See `docs/development/metric-lifecycle-process.md` for the authoritative guide on:
- Adding new metrics
- Deprecating metrics
- Removing metrics
```

### R3: Include Practical Examples

Add real examples from recent work to make the documentation concrete:
- Adding `cm_ltv_to_cac_ratio_by_cohort` (MET-5)
- Deprecating `cm_gmv`, `cm_bookings`, `cm_billings`, `cm_acv`, `cm_tcv` (MET-6)

## Deliverables

1. **Process document**: `docs/development/metric-lifecycle-process.md`
2. **CLAUDE.md update**: Reference to new process document
3. **Practical examples**: From MET-5 and MET-6 work
4. **Verification**: Checklist can be followed for future metric changes

## Verification

```bash
# Verify file exists
ls -la docs/development/metric-lifecycle-process.md

# Verify CLAUDE.md updated
grep -l "metric-lifecycle-process" CLAUDE.md

# Verify documentation renders correctly (if using markdown preview)
```

- Document is clear and complete
- All file paths are accurate
- Example SQL/YAML snippets are syntactically correct
- Process can be followed by someone unfamiliar with codebase

## Completion Checklist

- [ ] Create `docs/development/metric-lifecycle-process.md`
- [ ] Update CLAUDE.md with reference
- [ ] Include practical examples
- [ ] Verify all file paths are correct
- [ ] Update PROJECT_TASK_INVENTORY.md to mark MET-2 complete
- [ ] Archive this worker prompt to `docs/archive/worker-prompts-completed/`

## Out of Scope

- Actually adding or removing metrics (that's MET-5, MET-6)
- Changing any code or configuration
- Running gold standard validation

## Notes

- MET-10 was consolidated into this task (2026-01-07)
- This task was originally created but never executed

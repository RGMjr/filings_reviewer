# Metric Lifecycle Process

Version: 1.0
Date: 2026-01-07

## 1. Overview

This document provides the authoritative guide for adding, deprecating, and removing metrics in the Customer Metrics Filings Analysis system. Following this process ensures consistency across all system components.

### 1.1 Metric ID Naming Conventions

- All metric IDs **must** start with `cm_` (customer metric) prefix
- Use `snake_case` for multi-word names
- Be descriptive but concise
- Examples:
  - `cm_customers_period_end` (not `cm_cust_pe`)
  - `cm_net_revenue_retention` (not `cm_nrr`)
  - `cm_ltv_to_cac_ratio_by_cohort` (cohort variant of base metric)

### 1.2 Authoritative Source

The **YAML configuration** (`config/metric_keywords.yaml`) is the authoritative source for metric patterns and keyword matching. All other locations must stay synchronized with it.

### 1.3 Locations Where Metrics Are Defined

| Location | Purpose | Add | Deprecate | Remove |
|----------|---------|-----|-----------|--------|
| `config/metric_keywords.yaml` | Patterns, exclusions, aliases | Required | Keep (comment) | Remove |
| `sql/04_seed_metrics_taxonomy.sql` | Database seed, display names | Required | Update status | Remove |
| `src/web/routes/_metrics.py` | UI dropdown ordering | Required | Remove | Remove |
| `docs/development/metrics-taxonomy.md` | Business definitions | Required | Mark deprecated | Remove |

---

## 2. Adding a New Metric

Follow these steps in order. Each step includes the file path and example code.

### Step 1: Define in YAML Configuration

**File:** `config/metric_keywords.yaml`

Add a new metric block with patterns, exclusions (optional), specific_patterns (optional), required_context (optional), and aliases (optional).

```yaml
cm_new_metric_name:
  # Optional: aliases for gold standard compatibility
  aliases:
    - cm_alternate_name

  patterns:
    - '\bnew\s+metric\s+pattern\b'
    - '\balternate\s+pattern\b'

  # Optional: patterns that should NOT match this metric
  exclusions:
    - '\bexcluded\s+phrase\b'

  # Optional: multi-word patterns that get confidence bonus
  specific_patterns:
    - 'new\s+metric\s+pattern'

  # Optional: require context keywords nearby (for revenue synonyms)
  # Use YAML anchor <<: *revenue_synonym_context for standard context
  required_context:
    patterns:
      - '\bper\s+customer\b'
      - '\bcohort\b'
    proximity_chars: 1500
```

**Key considerations:**
- Use `\b` for word boundaries to prevent partial matches
- Use `\s+` for flexible whitespace between words
- Patterns are compiled with `re.IGNORECASE`
- Test patterns against real filing text before committing

### Step 2: Add to Database Seed

**File:** `sql/04_seed_metrics_taxonomy.sql`

Add an INSERT statement with all required fields.

```sql
-- New Metric Name (added YYYY-MM-DD: Brief reason)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_new_metric_name',
    'New Metric Display Name',
    'extended',  -- or 'core' for core metrics
    'Description explaining what this metric measures.',
    'primary_concept',  -- e.g., 'unit_economics', 'customer_count', 'retention'
    'active',
    1
);
```

**Metric classes:**
- `core` - Phase 1 core metrics (highest priority)
- `extended` - Phase 1 extended metrics (secondary priority)
- `future` - Phase 2+ metrics (anticipated but not active)

### Step 3: ~~Add to METRIC_NAME_MAPPING~~ (no longer needed)

This step is no longer required. The V2 pipeline uses pattern-based cohort classification in `src/extraction_v2/stages/fact_construction.py` and does not rely on a `METRIC_NAME_MAPPING` lookup. No changes to `value_extractor.py` are needed (that file was removed during the V1→V2 migration).

### Step 4: Add to Dropdown Ordering

**File:** `src/web/routes/_metrics.py`

Add to `METRIC_DISPLAY_ORDER` dict with the appropriate sort order based on category (see Section 5).

```python
METRIC_DISPLAY_ORDER: dict[str, int] = {
    # ... existing entries ...

    # Add in appropriate category range
    "cm_new_metric_name": 28,  # Revenue category (21-30)
}
```

> **Note:** `METRIC_DISPLAY_ORDER` is defined in `src/web/routes/_metrics.py` at line ~39.

### Step 5: Update Documentation

**File:** `docs/development/metrics-taxonomy.md`

Add the metric definition in the appropriate section (Core Metrics or Extended Metrics).

Include:
- Metric ID and class
- Business intent
- Canonical definition
- Units
- Required and optional dimensions
- Calculation rules
- What counts in Phase 1
- Common synonyms
- Out-of-scope items

### Step 6: Run Gold Standard Validation

```bash
# Run validation to check for regressions
pytest -m gold_standard --gold-standard-mode=fresh

# If intentional changes occurred, update baseline
python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```

### Step 7: Verify in UI

```bash
# Start Flask app
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python -m flask --app src.web.app run

# Navigate to review interface
# Confirm metric appears in dropdown at correct position
```

### Step 8: Run Tests

```bash
# Run all tests to ensure nothing is broken
pytest -v

# Run specific web tests for dropdown ordering
pytest tests/unit/web/test_review_routes.py -v
```

### Step 9: Chart-Bridge Considerations (Tier 1 cohort-style metrics only)

Most metrics are extracted exclusively from text and tables via Stages 6–10. A subset of Tier 1 cohort metrics is **also** extractable from chart images via the Chart Fact Bridge (`PipelineStage.CHART_FACT_BRIDGE`, runs after Stage 5). Current chart-bridge-supported metrics:

- `cm_revenue_by_cohort`
- `cm_balance_by_cohort`
- `cm_gross_margin_by_cohort`
- `cm_transactions_by_cohort`
- `cm_ltv_to_cac_ratio`

**No extra action required if your metric is text/table-only.** Skip this step.

**If your new metric is cohort-style and likely chart-embedded**, evaluate:

1. **Classifier scoring** — `src/extraction_v2/chart/metric_classifier.py` scores each `ChartData` against the same patterns defined in Step 1 (`config/metric_keywords.yaml`). No new config is required; the YAML patterns are shared. Score formula weighs title (3×specific, 2×patterns), y-axis (1.5×), x-axis + nearby_text (1×), annotations (0.8×), and subtracts exclusions (5×). A metric must score ≥ `PipelineConfig.chart_metric_classification_min_score` (default 0.6) to be emitted.

2. **Metric-specific gates** — hard gates beyond score (see `metric_classifier.py`). Example: `cm_balance_by_cohort` requires a "deposits"/"balance" token plus stacked-bar chart type. New chart-bridge metrics may need a gate added here to avoid false positives.

3. **Cohort signal requirement** — every cohort-style metric requires a cohort signal (year in series name OR "cohort"/"vintage" token in title/axis) as a hard gate, not a score contributor. `_COHORT_GATE_EXEMPT` in `metric_classifier.py` is the opt-out set for metrics (like `cm_ltv_to_cac_ratio`) that use tenure-bucket labels instead of vintage years.

4. **Cohort period parsing** — `src/extraction_v2/chart/cohort_parser.py` extracts `cohort_def` + `period_end` from `DataPoint.x` / `DataPoint.label` / `ChartSeries.name`. If your metric's chart shape doesn't match the existing vintage-year or elapsed-period regimes, extend the parser.

5. **Unit inference** — `src/extraction_v2/chart/unit_inference.py` maps `y_axis_label` to `Unit` + `currency`. Add mappings if your metric uses a unit not already handled (percent, ratio, currency+USD, count).

6. **Phase 3 hallucination guards** — all chart-bridge metrics inherit the five guards in `chart_fact_bridge.py` (image confidence, label required, axis range, cohort year, fact review threshold). See `docs/architecture/extraction-pipeline.md` §Hallucination Guards.

7. **Cross-source confirmation** — if your metric's chart value agrees with a text/table value for the same (metric, period, value) slot after deduplication, `DeduplicationStage._annotate_cross_source_confirmation` flags both facts as `cross_source_confirmed=True` and populates `confirming_source_types`. No action needed — this is automatic.

8. **Fixtures** — when adding chart-bridge coverage for a new metric, record a golden `ChartData` JSON fixture in `tests/fixtures/charts/<TICKER>_<chart-name>.chart_data.json` paired with the image file. Unit tests in `tests/extraction_v2/chart/` mock `vision_client.analyze_image` to return the fixture, so the test suite does not hit the real Vision API.

---

## 3. Deprecating a Metric

Use deprecation when a metric is no longer actively used but historical data exists. Deprecation preserves data integrity while hiding the metric from the UI.

### Step 1: Update Database Status

**File:** `sql/04_seed_metrics_taxonomy.sql`

Change `status` from `'active'` to `'deprecated'` and add a comment.

```sql
-- cm_old_metric_name (DEPRECATED YYYY-MM-DD: Reason for deprecation)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_old_metric_name',
    'Old Metric Name',
    'extended',
    'Description of the metric.',
    'primary_concept',
    'deprecated',  -- Changed from 'active'
    1
);
```

### Step 2: Keep in YAML (with comment)

**File:** `config/metric_keywords.yaml`

**DO NOT remove** - needed for historical data interpretation. Add a deprecation comment.

```yaml
# DEPRECATED YYYY-MM-DD: Reason for deprecation
cm_old_metric_name:
  patterns:
    - '\bold\s+metric\s+pattern\b'
```

### Step 3: ~~Keep in METRIC_NAME_MAPPING~~ (no longer applicable)

`src/extraction/value_extractor.py` was removed during the V1→V2 migration. The V2 pipeline uses pattern-based cohort classification in `src/extraction_v2/stages/fact_construction.py`. No action needed for this step.

### Step 4: Remove from Dropdown Ordering

**File:** `src/web/routes/_metrics.py`

Remove from `METRIC_DISPLAY_ORDER` dict so deprecated metrics don't appear in UI.

```python
METRIC_DISPLAY_ORDER: dict[str, int] = {
    # ... existing entries ...
    # "cm_old_metric_name": 28,  # REMOVED - deprecated YYYY-MM-DD
}
```

### Step 5: Update Documentation

**File:** `docs/development/metrics-taxonomy.md`

Mark as deprecated with date and reason.

```markdown
### 4.X Old Metric Name (DEPRECATED)

> **Deprecated:** YYYY-MM-DD
> **Reason:** Brief explanation of why deprecated (e.g., "Consolidated into cm_customers_period_end")

**ID:** `cm_old_metric_name`
**Class:** Extended (Phase 1)
...
```

### Step 6: Run Tests

```bash
# Run web tests to verify dropdown changes
pytest tests/unit/web/ -v

# Update any test fixtures that expect deprecated metric in dropdown
```

---

## 4. Removing a Metric Entirely

**WARNING:** Only remove metrics that were **never used in production**. If any data exists, use deprecation instead.

### Step 1: Check for Existing Data

```sql
-- Connect to database
psql $DATABASE_URL

-- Check for existing data
SELECT COUNT(*) FROM metric_values WHERE metric_id = 'cm_xxx';
SELECT COUNT(*) FROM review_candidates WHERE suggested_metric_id = 'cm_xxx';
SELECT COUNT(*) FROM review_decisions WHERE assigned_metric_id = 'cm_xxx';
SELECT COUNT(*) FROM filing_metric_incidence WHERE metric_id = 'cm_xxx';
```

**If any count > 0:** STOP and deprecate instead of removing.

### Step 2: Remove from All Locations (Reverse Order)

Remove in this order to avoid breaking references:

1. **Remove from dropdown ordering** (`src/web/routes/_metrics.py`)
   - Delete entry from `METRIC_DISPLAY_ORDER`

2. ~~**Remove from name mapping** (`src/extraction/value_extractor.py`)~~ — no longer applicable; this file was removed during the V1→V2 migration. No action needed.

3. **Remove INSERT statement** (`sql/04_seed_metrics_taxonomy.sql`)
   - Delete the entire INSERT block

4. **Remove from YAML** (`config/metric_keywords.yaml`)
   - Delete the entire metric block

5. **Remove from documentation** (`docs/development/metrics-taxonomy.md`)
   - Delete the metric section

### Step 3: Update Test Fixtures

Search for and update any test fixtures that reference the removed metric.

```bash
# Find references in tests
grep -r "cm_xxx" tests/
```

### Step 4: Run Full Test Suite

```bash
# Run all tests
pytest -v

# Run gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh
```

---

## 5. Metric Categories for Dropdown Ordering

The review UI dropdown organizes metrics into 5 semantic categories with defined sort order ranges:

| Category | Sort Range | Description | Example Metrics |
|----------|------------|-------------|-----------------|
| Customer Count Metrics | 1-10 | Headcount/user counts | `cm_customers_period_end` (1), `cm_daily_active_users` (3) |
| Transaction & Purchase Behavior | 11-20 | Orders, frequency, AOV | `cm_purchase_transactions_overall` (11), `cm_average_order_value` (14) |
| Revenue Metrics | 21-30 | ARR, MRR, ARPU, revenue by cohort | `cm_arr` (21), `cm_revenue_per_customer` (23) |
| Retention, Churn & Attrition | 31-40 | NRR, GRR, churn, retention | `cm_net_revenue_retention` (31), `cm_customer_churn_rate` (33) |
| Unit Economics & CAC | 41-50 | LTV, CAC, payback | `cm_lifetime_value_per_customer` (41), `cm_ltv_to_cac_ratio` (43) |

When adding a new metric, choose a sort order value within the appropriate category range.

---

## 6. Practical Examples

### Example A: Adding a Cohort Variant Metric

**Scenario:** Adding `cm_ltv_to_cac_ratio_by_cohort` (LTV:CAC ratio broken down by cohort)

**Changes required:**

1. **YAML** - Add patterns specific to cohort context:
   ```yaml
   cm_ltv_to_cac_ratio_by_cohort:
     patterns:
       - '\bltv[:/\s]+cac\s+(?:ratio\s+)?by\s+cohort\b'
       - '\bcohort\s+ltv[:/\s]+cac\b'
     specific_patterns:
       - 'ltv.{0,5}cac.{0,10}cohort'
   ```

2. **SQL** - Add INSERT with cohort-specific description:
   ```sql
   INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
   VALUES (
       'cm_ltv_to_cac_ratio_by_cohort',
       'LTV:CAC Ratio by Cohort',
       'extended',
       'Customer lifetime value to acquisition cost ratio, broken down by acquisition cohort.',
       'unit_economics',
       'active',
       1
   );
   ```

3. ~~**value_extractor.py**~~ - This step is no longer needed. The V2 pipeline handles metric classification in `src/extraction_v2/stages/fact_construction.py`.

4. **_metrics.py** - Add to Unit Economics category:
   ```python
   "cm_ltv_to_cac_ratio_by_cohort": 44,  # After cm_ltv_to_cac_ratio (43)
   ```

5. **metrics-taxonomy.md** - Add to Extended Metrics section:
   ```markdown
   ### 4.X LTV:CAC Ratio by Cohort

   **ID:** `cm_ltv_to_cac_ratio_by_cohort`
   **Class:** Extended (Phase 1)

   **Intent:** Customer lifetime value to acquisition cost ratio, segmented by
   acquisition cohort to show how unit economics vary by customer vintage.
   ```

### Example B: Deprecating Revenue Synonym Metrics

**Scenario:** Deprecating `cm_gmv`, `cm_bookings`, `cm_billings`, `cm_acv`, `cm_tcv` because they are too general without customer context

**Changes required:**

1. **SQL** - Change status to deprecated:
   ```sql
   -- cm_gmv (DEPRECATED 2026-01-07: Revenue synonym without inherent customer context)
   INSERT INTO metrics (..., status, ...)
   VALUES (..., 'deprecated', ...);
   ```

2. **YAML** - Add deprecation comments but keep patterns:
   ```yaml
   # DEPRECATED 2026-01-07: Revenue synonym - use required_context for customer metrics
   cm_gmv:
     patterns:
       - '\bgross\s+merchandise\s+value\b'
   ```

3. **_metrics.py** - Remove from `METRIC_DISPLAY_ORDER` dict

4. ~~**value_extractor.py**~~ - No longer applicable; this file was removed during the V1→V2 migration.

5. **metrics-taxonomy.md** - Mark deprecated:
   ```markdown
   ### 4.X GMV (DEPRECATED)

   > **Deprecated:** 2026-01-07
   > **Reason:** Revenue synonym without inherent customer context. Use `required_context`
   > in YAML for metrics that need cohort/per-customer context.

   **ID:** `cm_gmv`
   ...
   ```

6. **Run tests** - `pytest tests/unit/web/ -v` to verify dropdown changes

---

## 7. Checklist Template

Use this checklist when making metric changes:

### Adding a New Metric
- [ ] Added to `config/metric_keywords.yaml` with patterns
- [ ] Added INSERT to `sql/04_seed_metrics_taxonomy.sql`
- [ ] Added to `METRIC_DISPLAY_ORDER` in `src/web/routes/_metrics.py`
- [ ] Updated `docs/development/metrics-taxonomy.md`
- [ ] Ran `pytest -m gold_standard --gold-standard-mode=fresh`
- [ ] Verified metric appears in UI dropdown
- [ ] All tests passing

### Deprecating a Metric
- [ ] Changed status to `'deprecated'` in SQL
- [ ] Added deprecation comment in YAML (kept patterns)
- [ ] Removed from `METRIC_DISPLAY_ORDER` in `src/web/routes/_metrics.py`
- [ ] Marked deprecated in documentation
- [ ] All tests passing

### Removing a Metric
- [ ] Verified no existing data in database
- [ ] Removed from `METRIC_DISPLAY_ORDER` in `src/web/routes/_metrics.py`
- [ ] Removed INSERT from SQL
- [ ] Removed from YAML
- [ ] Removed from documentation
- [ ] Updated test fixtures
- [ ] All tests passing

---

## 8. Troubleshooting

### Metric not appearing in dropdown
1. Check that metric is in `METRIC_DISPLAY_ORDER` in `src/web/routes/_metrics.py`
2. Verify database has metric with `status = 'active'`
3. Restart Flask app to pick up code changes

### Gold standard validation failing
1. Run `python scripts/validate_against_gold_standard.py --all --mode fresh --baseline` to see delta
2. Check if patterns are too broad or too narrow
3. Review false positives/negatives in output

### Duplicate metric matches
1. Check for overlapping patterns in YAML
2. Add exclusions to more specific metric
3. Consider using `specific_patterns` for confidence differentiation

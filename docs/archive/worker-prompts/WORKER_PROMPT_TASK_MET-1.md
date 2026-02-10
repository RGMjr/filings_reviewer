# Worker Prompt: MET-1 - Metric Consistency Audit

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-1 |
| Task Name | Metric Consistency Audit |
| Size | L (4-8 hours) |
| Priority | High |
| Dependencies | None |
| Blocking | MET-3, MET-4 |

## Objective

Audit all metric definitions across the codebase to ensure consistency between the authoritative source (`config/metric_keywords.yaml`) and other locations. This is a **two-phase task**:

1. **Phase 1 (Audit)**: Generate a comprehensive audit report identifying all discrepancies
2. **Phase 2 (Fix)**: After user review of the audit report, fix approved inconsistencies

**IMPORTANT**: Do not proceed to Phase 2 without explicit user approval of the audit findings.

## Background

Metrics are defined in multiple locations throughout the codebase:
1. **Authoritative source**: `config/metric_keywords.yaml` - patterns, exclusions, aliases
2. **Database seed**: `sql/04_seed_metrics_taxonomy.sql` - display names, classes, descriptions
3. **Python mapping**: `src/extraction/value_extractor.py` - METRIC_NAME_MAPPING dict
4. **Test fixtures**: Various test files with hardcoded metric IDs

### Known Design Issue: Alias Conflict

The YAML declares `cm_active_customers_total` as an **alias** for `cm_customers_period_end`:
```yaml
cm_customers_period_end:
  aliases:
    - cm_active_customers_total
```

But `cm_active_customers_total` also exists as a **standalone metric** in:
- The SQL seed file (with its own INSERT statement)
- The YAML (with its own patterns for "active customers/users/accounts")

**Semantic question**: Are these truly equivalent (alias) or distinct (one = engagement-based "active", other = period-end stock count)?

**Action**: Document this conflict in the audit report. Do NOT resolve without user guidance.

## Requirements

### Phase 1: Audit (R1-R6)

#### R1: Extract Canonical Metric List
- Parse `config/metric_keywords.yaml` to get all metric IDs (keys starting with `cm_`)
- Extract aliases for each metric
- Note deprecated status from comments (e.g., `# DEPRECATED 2026-01-07`)
- This is the authoritative list

#### R2: Audit Database Seed File
- Parse `sql/04_seed_metrics_taxonomy.sql`
- Compare metric IDs to canonical list
- Flag:
  - Missing metrics (in YAML but not in SQL)
  - Extra metrics (in SQL but not in YAML)
  - Status inconsistencies (deprecated in one, active in other)
  - **Alias conflicts** (metrics that are both aliases AND standalone)

#### R3: Audit METRIC_NAME_MAPPING
- Parse `src/extraction/value_extractor.py` METRIC_NAME_MAPPING dict
- Compare target values to canonical list
- Flag:
  - Mappings to non-existent metric IDs
  - Missing mappings for active canonical metrics (note: not all metrics need LLM mappings)

#### R4: Audit Test Fixtures
- Search for hardcoded metric IDs in `tests/` directory
- Categorize findings:
  - **Clearly wrong**: IDs that don't exist and aren't abbreviations (e.g., `cm_gross_retention` should be `cm_gross_revenue_retention`)
  - **Abbreviated**: Short forms that may be intentional for tests (e.g., `cm_dau` for `cm_daily_active_users`)
  - **Valid**: IDs that match canonical list or known aliases
- List all unique metric IDs used in tests

#### R5: Check for Missing Patterns
- For each metric in SQL that has `status = 'active'`, verify YAML has patterns
- Flag metrics that exist in SQL but have no detection patterns in YAML

#### R6: Generate Audit Report
Create `docs/reports/MET-1-metric-consistency-audit.md` with:
- Executive summary (total metrics, discrepancy counts by severity)
- Canonical metric list from YAML (with aliases and deprecation status)
- SQL vs YAML comparison table
- METRIC_NAME_MAPPING gaps
- Test fixture issues (categorized as above)
- **Design issue**: Document the alias conflict with recommendation
- Recommended fixes (prioritized by risk/impact)

**STOP after R6. Present audit report to user for review before proceeding.**

### Phase 2: Fix (R7-R8) - Requires User Approval

#### R7: Fix Approved Inconsistencies
Based on user feedback on the audit report:
- Update SQL seed file (if approved)
- Update METRIC_NAME_MAPPING (if approved)
- Fix clearly wrong test fixture IDs (if approved)
- Do NOT modify `config/metric_keywords.yaml` (that's the source of truth)
- Do NOT change abbreviated test IDs unless user explicitly approves

#### R8: Validate Changes
- Run gold standard validation (required per CLAUDE.md)
- Run all affected tests
- Verify no regressions

## Files to Audit

| File | Type | Check |
|------|------|-------|
| `config/metric_keywords.yaml` | Config | SOURCE OF TRUTH |
| `sql/04_seed_metrics_taxonomy.sql` | SQL | Metric IDs, display_name, status |
| `src/extraction/value_extractor.py` | Python | METRIC_NAME_MAPPING dict |
| `tests/**/*.py` | Tests | Hardcoded metric IDs |

## Verification Commands

```bash
# Phase 1: Verify YAML is valid
python -c "import yaml; yaml.safe_load(open('config/metric_keywords.yaml'))"

# Phase 1: List all metric IDs in tests
grep -r "cm_" tests/ | grep -v "__pycache__" | grep -oE "cm_[a-z_]+" | sort | uniq

# Phase 2: After fixes, run gold standard validation (REQUIRED)
pytest -m gold_standard --gold-standard-mode=fresh -v

# Phase 2: Run affected tests
pytest tests/unit/extraction/test_value_extractor.py -v --tb=short
pytest tests/unit/web/ -v --tb=short
pytest tests/performance/ -v --tb=short --no-cov
```

## Deliverables

### Phase 1
1. **Audit report**: `docs/reports/MET-1-metric-consistency-audit.md`

### Phase 2 (after approval)
2. **Fixed files**: Approved locations synchronized with YAML
3. **All tests pass**: Including gold standard validation
4. **No regressions**: Gold standard metrics unchanged or improved

## Out of Scope

- Adding new metrics (that's MET-5)
- Deprecating metrics (that's MET-6)
- Changing extraction logic
- Modifying `config/metric_keywords.yaml`
- **Documentation updates**: `docs/development/metrics-taxonomy.md` is significantly out of date (v0.1 from Nov 2025). Updating it is a separate task - create follow-up task MET-7 if needed.
- Resolving the alias design conflict (requires architectural decision)

## Completion Checklist

### Phase 1: Audit
- [ ] Extract canonical metric list from YAML
- [ ] Audit database seed file
- [ ] Audit METRIC_NAME_MAPPING
- [ ] Audit test fixtures (categorize findings)
- [ ] Check for missing patterns
- [ ] Generate audit report to `docs/reports/MET-1-metric-consistency-audit.md`
- [ ] **STOP**: Present audit report to user for review

### Phase 2: Fix (after user approval)
- [ ] Fix approved SQL inconsistencies
- [ ] Fix approved METRIC_NAME_MAPPING gaps
- [ ] Fix approved test fixture errors
- [ ] Run gold standard validation (must pass)
- [ ] Run all verification commands (all tests pass)
- [ ] Create follow-up task for documentation update if needed
- [ ] Update PROJECT_TASK_INVENTORY.md to mark MET-1 complete
- [ ] Archive this worker prompt to `docs/archive/worker-prompts-completed/`

## Notes

### Alias System
- Aliases are defined in YAML under each metric's `aliases` field
- Functions in `src/extraction/keyword_config.py`: `get_aliases()`, `resolve_to_canonical()`, `get_all_equivalent_ids()`, `metrics_are_equivalent()`
- System always generates canonical IDs; aliases only used for comparison/validation

### Test Fixture Considerations
- Performance tests (`tests/performance/`) often use simplified metric IDs for readability
- Unit tests may intentionally use non-canonical IDs to test mapping behavior
- Only fix IDs that are clearly errors (e.g., typos, wrong suffixes)

### Deprecated Metrics
The following metrics are marked deprecated in both YAML and SQL:
- `cm_bookings`, `cm_billings` (financial metrics, not customer metrics)
- `cm_gmv`, `cm_acv`, `cm_tcv` (financial metrics unless cohort-specific)
- `cm_gross_margin_overall` (not customer-specific)

These should remain in sync but are not actively used.

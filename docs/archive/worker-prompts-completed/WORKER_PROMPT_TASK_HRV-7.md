# WORKER PROMPT: Task HRV-7 - Metric ID Normalization (System-Wide)

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-7
TASK NAME:     Clean up deprecated code in MetricClassifier and ensure alias system works correctly
WORKSTREAM:    Human Review Validation - System Improvements
SOURCE:        docs/PROJECT_TASK_INVENTORY.md (Phase 4b)
STATUS:        🟡 PENDING
COMPLETION:    [Path to completion summary, if complete]
TIME ESTIMATE: 1-2 hours (cleanup 45 min, verification 45 min)
TIME ACTUAL:   [Actual time taken, if complete]
RISK LEVEL:    Low (code cleanup only, no behavior changes)
TASK SIZE:     S
DEPENDS ON:    HRV-4 (Farfetch validation complete)
UNLOCKS:       HRV-15 (Candidate regeneration)
BLOCKS:        None
PARALLEL WITH: HRV-9, HRV-12
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Clean up deprecated hardcoded dictionaries in `metric_classifier.py` and verify the metric ID alias system works correctly for gold standard validation.

**Business Rationale**: The MetricClassifier contains deprecated hardcoded `METRIC_KEYWORDS` and `METRIC_REQUIRED_CONTEXT` dictionaries that are no longer used (YAML is the source of truth). This tech debt creates confusion and makes the codebase harder to maintain. Cleaning this up improves code clarity without changing any behavior.

**Current Behavior**:
- `metric_classifier.py` contains ~400 lines of deprecated hardcoded dictionaries (lines 118-404 and 449-475)
- Comments say "DEPRECATED" but code is still present
- New developers may be confused about which source of truth to use

**Desired Behavior**:
- Deprecated dictionaries removed or clearly isolated
- Code comments updated to clarify YAML is sole source of truth
- Alias system verified to work correctly in validation script

## Prerequisites

- HRV-4 complete (Farfetch validation analysis provides context)
- Understanding of `keyword_config.py` alias system
- YAML config is functioning (already verified)

## Files to Modify

1. **`src/extraction/metric_classifier.py`** - Remove or isolate deprecated dictionaries, update comments
2. **`src/extraction/keyword_config.py`** - Add docstring clarifications if needed
3. **`docs/PROJECT_TASK_INVENTORY.md`** - Mark HRV-7 complete

## Files to Read (Context Only)

- `config/metric_keywords.yaml` - Current authoritative keyword patterns
- `scripts/validate_against_gold_standard.py` - Uses `metrics_are_equivalent()` for matching
- `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` - Context on metric ID issues

## Implementation Requirements

### Core Functionality

1. **Clean Up Deprecated Code**
   - Remove or relocate the deprecated `METRIC_KEYWORDS` dictionary (~280 lines)
   - Remove or relocate the deprecated `METRIC_REQUIRED_CONTEXT` dictionary (~25 lines)
   - Option A: Delete entirely (recommended - YAML is source of truth)
   - Option B: Move to a separate `_deprecated.py` file for reference
   - Update class docstring to clarify YAML is sole source of truth

2. **Verify Alias System**
   - Confirm `metrics_are_equivalent()` handles current aliases correctly
   - Test that `cm_customers_period_end` matches `cm_active_customers_total`
   - Run validation script to verify no regression

3. **Documentation Updates**
   - Update any references that mention hardcoded patterns
   - Ensure CLAUDE.md design decision #12 (alias system) is still accurate

### Error Handling

- No new error handling needed (cleanup task)
- Ensure existing tests still pass after cleanup

### Backward Compatibility

- **No behavior changes**: This task only removes dead code
- **YAML is already the source**: `_load_keywords()` loads from YAML, not hardcoded dict
- **Tests verify behavior**: Existing tests ensure patterns still work

## Test Requirements

### Coverage Target: Maintain existing coverage for `metric_classifier.py`

### Test Categories (verify only, no new tests needed)

1. **Existing Tests**
   - All `tests/unit/extraction/test_metric_classifier.py` tests must pass
   - All `tests/unit/extraction/test_keyword_config.py` tests must pass

2. **Alias System Verification**
   - Verify `metrics_are_equivalent("cm_customers_period_end", "cm_active_customers_total")` returns True
   - Verify `resolve_to_canonical("cm_active_customers_total")` returns `"cm_customers_period_end"`

## Gold Standard Validation

This task cleans up code but does NOT modify keyword patterns or extraction logic. However, verify no regression:

```bash
# Quick check that alias matching still works
python3 -c "
from src.extraction.keyword_config import metrics_are_equivalent, resolve_to_canonical
assert metrics_are_equivalent('cm_customers_period_end', 'cm_active_customers_total')
assert resolve_to_canonical('cm_active_customers_total') == 'cm_customers_period_end'
print('Alias system working correctly')
"
```

## Acceptance Criteria

- [ ] Deprecated `METRIC_KEYWORDS` dictionary removed from `metric_classifier.py`
- [ ] Deprecated `METRIC_REQUIRED_CONTEXT` dictionary removed from `metric_classifier.py`
- [ ] Class docstrings updated to clarify YAML is source of truth
- [ ] All existing unit tests pass
- [ ] Alias system verification passes
- [ ] `mypy src/extraction/metric_classifier.py --strict` passes
- [ ] NO changes to keyword patterns or matching behavior
- [ ] `docs/PROJECT_TASK_INVENTORY.md` updated to mark HRV-7 complete

## Do NOT

- Modify `config/metric_keywords.yaml` (no pattern changes)
- Change any matching/classification behavior
- Add new aliases (out of scope)
- Modify `src/review/` modules (HRV-9, HRV-12 work in those files)

## Verification Commands

```bash
# Run metric_classifier tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_metric_classifier.py -v --no-cov

# Run keyword_config tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_keyword_config.py -v --no-cov

# Type safety check
mypy src/extraction/metric_classifier.py --strict

# Verify alias system
python3 -c "
from src.extraction.keyword_config import metrics_are_equivalent, resolve_to_canonical, get_aliases
aliases = get_aliases()
print('Aliases defined:', aliases)
assert metrics_are_equivalent('cm_customers_period_end', 'cm_active_customers_total')
assert resolve_to_canonical('cm_active_customers_total') == 'cm_customers_period_end'
print('All alias checks passed')
"

# Verify MetricClassifier still loads from YAML
python3 -c "
from src.extraction.metric_classifier import MetricClassifier
classifier = MetricClassifier()
print(f'Loaded {len(classifier._metric_patterns)} metric patterns from YAML')
assert len(classifier._metric_patterns) >= 30, 'Expected 30+ metrics from YAML'
print('MetricClassifier loading correctly from YAML')
"
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] Comments clearly explain YAML is source of truth
- [ ] No remnants of deprecated code left behind

### 2. Test Coverage Assessment
- [ ] Existing tests still pass
- [ ] No new test gaps introduced

### 3. Architecture Alignment
- [ ] Follows CLAUDE.md design decision #8 (externalized keyword config)
- [ ] Follows CLAUDE.md design decision #12 (alias system)

### 4. Identify Improvements
Document any potential improvements discovered:
- Additional aliases that might be needed
- Documentation gaps
- Other deprecated code to clean up

### 5. User Approval (REQUIRED)
**STOP and ask the user** before committing.

## Expected Impact

**Before HRV-7**:
- ~400 lines of deprecated code in metric_classifier.py
- Potential confusion about source of truth

**After HRV-7**:
- Clean codebase with YAML as sole source of truth
- ~400 lines of dead code removed
- Clearer documentation

## Reference

- **Issue source**: PROJECT_TASK_INVENTORY.md Phase 4b
- **Dependencies**: HRV-4 (complete)
- **Related**: CLAUDE.md design decisions #8 and #12

---

**Last Updated**: 2026-01-01
**Format Version**: 2.6

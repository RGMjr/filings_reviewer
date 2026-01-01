# WORKER PROMPT: Task GR-11 - Extract Formula Configuration

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-11
TASK NAME:     Create FormulaWeights dataclass for configurable scoring
WORKSTREAM:    Refactoring
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 2 Code Quality
STATUS:        🟡 PENDING
TIME ESTIMATE: 3 hours (design 45 min, implementation 90 min, testing 45 min)
RISK LEVEL:    LOW (refactoring, backward compatible)
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    None
UNLOCKS:       A/B testing of formula weights, easier tuning experiments
BLOCKS:        None
PARALLEL WITH: GR-12, GR-13, GR-14, GR-16, GR-17
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Extract all hardcoded formula constants from segment_enricher.py into a configurable FormulaWeights dataclass, enabling A/B testing of scoring formulas and easier experimentation.

**Business Rationale**: Currently, tuning the richness score formula requires modifying hardcoded values scattered throughout segment_enricher.py. A centralized configuration enables:
- A/B testing different weight combinations
- Easier experimentation without code changes
- Better documentation of formula components
- Simpler unit testing of formula variations

**Current Behavior**: Weights like `+1.0` for numeric values, `+0.75` for usage context, `+0.5` for basic matches are hardcoded throughout `_calculate_richness_score()` and `_enrich_segment()`.

**Desired Behavior**: All weights centralized in a FormulaWeights dataclass, injected into SegmentEnricher, with defaults matching current behavior.

## Prerequisites

- None (standalone refactoring)
- Understanding of current formula structure in segment_enricher.py helpful

## Files to Create

1. **`src/extraction/enricher_config.py`** - New file with FormulaWeights dataclass

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Accept weights in __init__, use throughout
2. **`tests/unit/extraction/test_segment_enricher_richness.py`** - Test configurable weights

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 990-1033 - Current `_calculate_richness_score()` method
- `src/extraction/segment_enricher.py` lines 1000-1020 - Tiered usage bonus logic
- `docs/GOLDMINE_REMEDIATION_PLAN.md` - Context on formula evolution

## Implementation Requirements

### Core Functionality

1. **Create FormulaWeights Dataclass**

   Create `src/extraction/enricher_config.py`:
   ```python
   from dataclasses import dataclass

   @dataclass(frozen=True)
   class FormulaWeights:
       """Configuration for richness score calculation."""

       # Base component weights
       keyword_density_weight: float = 0.25
       metric_type_weight: float = 0.20
       numeric_presence_weight: float = 0.15
       context_quality_weight: float = 0.15
       definition_flag_weight: float = 0.10
       temporal_cohort_weight: float = 0.15

       # Bonus values
       usage_with_count_bonus: float = 1.0
       usage_with_context_bonus: float = 0.75
       usage_basic_bonus: float = 0.5
       definition_tier1_bonus: float = 0.75
       definition_tier2_bonus: float = 0.5

       # Thresholds (optional, if useful)
       goldmine_threshold: float = 5.5

       @classmethod
       def default(cls) -> "FormulaWeights":
           """Return default weights matching current production behavior."""
           return cls()
   ```

2. **Update SegmentEnricher.__init__**
   - Add optional `weights: FormulaWeights | None = None` parameter
   - Default to `FormulaWeights.default()` if None
   - Store as `self.weights`

3. **Replace Hardcoded Values**
   - Find all hardcoded bonus values in `_calculate_richness_score()`
   - Replace with `self.weights.*` references
   - Example: `score += 1.0` becomes `score += self.weights.usage_with_count_bonus`

4. **Maintain Backward Compatibility**
   - Existing code calling `SegmentEnricher()` with no args should work unchanged
   - All default weights must match current hardcoded values exactly
   - Tests should pass without modification

### Error Handling

- **Invalid weights**: Dataclass is frozen, so invalid values raise on construction
- **Negative weights**: Consider adding validation in dataclass __post_init__

### Test Requirements

#### Coverage Target: **Maintain existing coverage** for `segment_enricher.py`

#### Test Categories (10+ tests)

1. **Default Weights Tests** (3-4 tests)
   - Default weights produce same scores as before
   - FormulaWeights.default() returns expected values
   - SegmentEnricher() with no args uses defaults

2. **Custom Weights Tests** (4-5 tests)
   - Custom weights modify scores as expected
   - Higher usage_with_count_bonus increases usage segment scores
   - Lower threshold affects goldmine classification
   - Zero weights disable specific bonuses

3. **Backward Compatibility Tests** (3 tests)
   - Existing test cases produce identical scores
   - No regression in goldmine detection
   - Richness calculation unchanged for all test segments

### Known Edge Cases to Test

- Weights of 0.0 (should disable that component)
- Very large weights (should still produce valid scores)
- Frozen dataclass prevents modification after creation

## Acceptance Criteria

- [ ] `src/extraction/enricher_config.py` created with FormulaWeights dataclass
- [ ] FormulaWeights contains all hardcoded formula constants
- [ ] SegmentEnricher accepts optional `weights` parameter
- [ ] All hardcoded values replaced with `self.weights.*` references
- [ ] Default weights match current production values exactly
- [ ] All existing tests pass without modification
- [ ] 10+ new tests covering weight configuration
- [ ] `mypy src/extraction/enricher_config.py --strict` passes

## Do NOT

- Change default weight values (must match current hardcoded values)
- Modify formula logic (only extract constants)
- Add complexity beyond simple extraction (no caching, no optimization)
- Create dependency on external config files (keep in-code dataclass)

## Verification Commands

```bash
# Run enricher tests to verify no regression
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Run richness-specific tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher_richness.py -v --tb=short

# Type safety check
mypy src/extraction/enricher_config.py --strict

# Verify dataclass structure
python3 -c "from src.extraction.enricher_config import FormulaWeights; print(FormulaWeights.default())"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# src/extraction/enricher_config.py
from dataclasses import dataclass

@dataclass(frozen=True)
class FormulaWeights:
    """Configurable weights for richness score calculation."""

    # Usage bonus tiers (lines 1010-1017 in segment_enricher.py)
    usage_with_count_bonus: float = 1.0
    usage_with_context_bonus: float = 0.75
    usage_basic_bonus: float = 0.5

    # Definition bonus tiers
    definition_high_value_bonus: float = 0.75
    definition_basic_bonus: float = 0.5

    # ... other weights from formula

    @classmethod
    def default(cls) -> "FormulaWeights":
        return cls()

    @classmethod
    def high_precision(cls) -> "FormulaWeights":
        """Weights tuned for high precision (fewer false positives)."""
        return cls(
            usage_basic_bonus=0.25,  # Lower bonus for basic matches
            # ... other adjustments
        )


# Usage in segment_enricher.py
class SegmentEnricher:
    def __init__(self, weights: FormulaWeights | None = None):
        self.weights = weights or FormulaWeights.default()

    def _calculate_richness_score(self, ...) -> float:
        # Instead of: score += 1.0
        score += self.weights.usage_with_count_bonus
```
</details>

## Expected Impact

**Before GR-11**:
- Weights scattered as magic numbers throughout code
- A/B testing requires code changes
- Hard to document formula components

**After GR-11**:
- Centralized, documented weight configuration
- Easy A/B testing with different FormulaWeights instances
- Clear formula specification in dataclass

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4

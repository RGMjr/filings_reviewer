# WORKER PROMPT: Task HRV-12 - Industry-Specific Keyword Weighting

> **⚠️ TASK CLOSED - WON'T DO (2026-01-03)**
>
> This task was closed after critical evaluation revealed it addresses the wrong problem:
>
> 1. **Top FP causes are NOT industry-related**: Financial statement values (35%), percentage misclassification (20%), table row spillover (15%)
> 2. **Farfetch's low metrics were due to taxonomy mismatch**: Fixed in PR1/PR2 by remapping "Number of Orders" to correct metric ID
> 3. **Circular dependency**: Industry detection from keywords (detect GMV → e-commerce) then boosting those same keywords is circular
> 4. **Context-gating already exists**: `required_context` in YAML already gates revenue synonyms by cohort/per-customer context
> 5. **HRV-6 Section 4 recommends pattern additions**: Not industry weighting
>
> See `docs/PROJECT_TASK_INVENTORY.md` for HRV-12 closure note.
>
> **Note**: The actual FP root causes are already addressed by completed tasks:
> - HRV-8: Percentage filter (20% of FPs)
> - HRV-10/11: Financial statement filtering (35% of FPs)
> - HRV-17: Table row spillover (15% of FPs)

```
===============================================================================
TASK ID:       HRV-12
TASK NAME:     Implement industry-specific keyword weighting for improved precision
WORKSTREAM:    Human Review Validation (Phase 4c)
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md, HRV-6 Validation Analysis Section 4
STATUS:        ❌ CLOSED (Won't Do)
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (design 30min, implementation 90min, testing 60min)
TIME ACTUAL:   N/A (not executed)
RISK LEVEL:    LOW - Additive changes to keyword matching; existing behavior preserved
TASK SIZE:     M
DEPENDS ON:    HRV-9 (growth metric removal - complete)
UNLOCKS:       HRV-15 (candidate regeneration), HRV-16 (validation re-run)
BLOCKS:        None
PARALLEL WITH: HRV-20 (no file conflicts)
CLOSED:        2026-01-03 - Critical evaluation showed wrong problem being addressed
===============================================================================
```

## Objective

Add industry-specific keyword weighting to improve precision for different company verticals. The HRV-6 validation analysis revealed significant performance differences: Enterprise SaaS (Slack) achieves 76% precision vs Fashion E-commerce (Farfetch) at 40% precision.

**Business Rationale**: Different industries use different terminology for customer metrics. SaaS companies use "customers" and "ARR", while e-commerce uses "consumers" and "orders". Industry-aware weighting lets us boost or penalize keywords based on the filing's industry, reducing false positives.

**Current Behavior**:
- All keyword patterns have uniform weighting regardless of company industry
- "Active Consumers" pattern works well for Farfetch but may false-positive in SaaS filings
- SaaS-specific patterns (ARR thresholds) may false-positive in e-commerce filings
- No mechanism to adjust confidence based on industry context

**Desired Behavior**:
- Keywords can have industry-specific weight modifiers (e.g., "consumers" boosted for e-commerce)
- Industry classification available from company metadata or detected from filing content
- Confidence scores adjusted by industry context during candidate generation
- Backward compatible: filings without industry classification use default weights

## Prerequisites

- HRV-9 complete (growth metric removal)
- Understanding of `config/metric_keywords.yaml` structure
- Understanding of `KeywordMatcher` in `src/review/keyword_matching.py`
- Understanding of how confidence scores are computed in candidate generation

## Files to Read (Context Only)

- `docs/analysis/HRV-6_VALIDATION_ANALYSIS.md` - Section 4 (Industry-Specific Insights)
- `src/review/config.py` - Current CandidateGenerationConfig structure
- `src/universe/classifiers.py` - Existing industry classification logic (if any)
- `src/infra/db.py` - Company/filing metadata access patterns

## Files to Modify

1. **`config/metric_keywords.yaml`** - Add industry_weights section to relevant metrics
2. **`src/review/keyword_matching.py`** - Apply industry weights during matching
3. **`src/review/config.py`** - Add industry weighting configuration options
4. **`src/extraction/metric_classifier.py`** - Pass industry context if available

## Implementation Requirements

### Core Functionality

1. **Industry Classification Source**
   - Determine industry from company metadata (if `industry` field exists in `companies` table)
   - Fallback: Detect industry from filing content patterns (heuristic-based)
   - Support at minimum: `saas`, `ecommerce`, `fintech`, `default` (unknown)
   - Industry should be optional - missing industry uses default weights

2. **YAML Configuration Extension**
   - Add optional `industry_weights` section to metrics in `metric_keywords.yaml`
   - Structure: `industry_weights: { saas: 1.2, ecommerce: 0.8, default: 1.0 }`
   - Weights multiply the base confidence score (>1.0 = boost, <1.0 = penalize)
   - Metrics without `industry_weights` use 1.0 (no adjustment)

3. **Weight Application**
   - Apply industry weight during `find_keywords_near_number()` or during confidence scoring
   - Industry weight affects the effective distance or confidence, not keyword detection itself
   - Log when industry weight is applied for monitoring

4. **Industry Detection Heuristics** (if company metadata unavailable)
   - E-commerce signals: "GMV", "orders", "consumers", "marketplace", "take rate", "AOV"
   - SaaS signals: "ARR", "MRR", "NRR", "subscription", "seats", "enterprise"
   - Fintech signals: "AUM", "deposits", "loans", "trading volume"
   - Return detected industry with confidence score

### Recommended Industry Weights (from HRV-6 analysis)

| Metric Pattern | SaaS | E-commerce | Default |
|----------------|------|------------|---------|
| "consumers" variants | 0.7 | 1.3 | 1.0 |
| "customers" variants | 1.2 | 0.9 | 1.0 |
| ARR/MRR patterns | 1.3 | 0.6 | 1.0 |
| Orders/transactions | 0.7 | 1.3 | 1.0 |
| GMV patterns | 0.6 | 1.3 | 1.0 |
| Take Rate/AOV | 0.7 | 1.3 | 1.0 |

### Error Handling

- **Missing industry**: Use default weight (1.0) - no error
- **Invalid industry in config**: Log warning, use default weight
- **Industry weight outside 0.1-3.0 range**: Clamp to range, log warning
- **YAML parsing errors**: Fail fast with clear error message

### Performance Requirements

- Industry detection heuristics: <10ms per filing
- Weight lookup from config: <1ms (cached at load time)
- No measurable impact on overall candidate generation time

### Backward Compatibility

- Metrics without `industry_weights` behave exactly as before (weight = 1.0)
- Industry detection is optional - None/unknown uses default weights
- No changes to candidate output schema - industry weight is internal
- All existing tests must continue to pass

## Test Requirements

### Coverage Target: **>= 90%** for new code in `keyword_matching.py`

### Test Categories (15+ tests recommended)

1. **Weight Application Tests** (5-6 tests)
   - Weight > 1.0 boosts keyword confidence
   - Weight < 1.0 penalizes keyword confidence
   - Weight = 1.0 has no effect
   - Missing industry uses default weight
   - Weight clamping at boundaries (0.1, 3.0)

2. **YAML Configuration Tests** (4-5 tests)
   - Parse industry_weights from YAML correctly
   - Handle metrics without industry_weights
   - Handle malformed industry_weights gracefully
   - Verify default weights for unlisted industries

3. **Industry Detection Tests** (4-5 tests)
   - Detect e-commerce from GMV/orders/consumers keywords
   - Detect SaaS from ARR/MRR/subscription keywords
   - Return "default" when no clear signals
   - Handle empty/minimal text gracefully

4. **Integration Tests** (2-3 tests)
   - Full flow: industry detection -> weight lookup -> candidate score adjustment
   - Verify Farfetch filing uses e-commerce weights
   - Verify Slack filing uses SaaS weights (or default)

### Known Edge Cases to Test

- Filing with mixed industry signals (some SaaS, some e-commerce keywords)
- Very short segments with no industry signals
- Multiple industries detected with similar confidence

## Gold Standard Validation

This task modifies `config/metric_keywords.yaml` and `src/review/keyword_matching.py`. Gold standard validation is **required** before commit.

### Validation Commands

```bash
# Quick check during development
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

# Formal validation (must pass before commit)
pytest -m gold_standard --gold-standard-mode=fresh -v
```

### Expected Impact on Metrics

- Farfetch precision: improve from 40% toward 50%+ (e-commerce weights boost relevant patterns)
- Slack precision: maintain at 76%+ (SaaS weights already natural fit)
- Overall F1: improve by reducing industry-specific false positives

## Acceptance Criteria

- [ ] Industry weights configurable in `metric_keywords.yaml` with documented structure
- [ ] At least 5 metric patterns have industry-specific weights defined
- [ ] `KeywordMatcher` applies industry weights to effective distance or confidence
- [ ] Industry detection heuristic implemented (or industry passed from company metadata)
- [ ] **15+ unit tests** covering weight application, YAML parsing, industry detection
- [ ] **Test coverage >= 90%** for new code
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] Gold standard validation shows no regressions
- [ ] `mypy src/review/keyword_matching.py --strict` passes

## Do NOT

- Modify `src/review/table_structure.py` (separate concern, HRV-17 scope)
- Add new dependencies to requirements.txt
- Change the candidate output schema (industry weight is internal scoring only)
- Remove or rename existing keyword patterns
- Over-engineer industry detection (simple heuristics are sufficient)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py -v -k "industry"

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py \
  --cov=src/review/keyword_matching --cov-report=term-missing

# Type safety check
mypy src/review/keyword_matching.py --strict

# Full test suite (ensure no regressions)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q

# Gold standard validation
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## Auto-Generated Verification Script

Copy this entire block to verify all acceptance criteria in one command:

```bash
#!/bin/bash
# Auto-generated verification for Task HRV-12: Industry-Specific Keyword Weighting
# Run: bash verify_hrv12.sh

set -e  # Exit on any error
echo "==============================================================="
echo "Verifying Task HRV-12: Industry-Specific Keyword Weighting"
echo "==============================================================="

# Check YAML has industry_weights
echo "Checking: industry_weights in YAML..."
grep -q "industry_weights" config/metric_keywords.yaml || { echo "FAIL: No industry_weights in YAML"; exit 1; }
echo "PASS: industry_weights found in YAML"

# Check at least 5 metrics have weights
echo "Checking: >= 5 metrics with industry_weights..."
COUNT=$(grep -c "industry_weights:" config/metric_keywords.yaml || echo 0)
[ "$COUNT" -ge 5 ] || { echo "FAIL: Only $COUNT metrics have industry_weights (need >= 5)"; exit 1; }
echo "PASS: $COUNT metrics have industry_weights"

# Type safety
echo "Checking: mypy passes..."
mypy src/review/keyword_matching.py --strict

# Test coverage (must be >= 90%)
echo "Checking: Test coverage >= 90%..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py \
  --cov=src/review/keyword_matching --cov-report=term --cov-fail-under=90 -q

# Full test suite
echo "Checking: All unit tests pass..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q

# Gold standard validation
echo "Checking: Gold standard validation..."
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline

echo "==============================================================="
echo "All acceptance criteria verified for Task HRV-12!"
echo "==============================================================="
```

## Critical Evaluation Phase

**Required for all tasks. Depth: M (Thorough evaluation)**

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] Industry weight logic is simple and maintainable
- [ ] YAML structure is well-documented
- [ ] Logging is informative but not verbose

### 2. Test Coverage Assessment
- [ ] All edge cases from requirements are covered
- [ ] Negative tests exist (invalid weights, missing industry)
- [ ] Integration with existing keyword matching is tested

### 3. Architecture Alignment
- [ ] Solution follows CLAUDE.md patterns (rule-based first, conservative classification)
- [ ] Changes are minimal and focused
- [ ] No over-engineering of industry detection

### 4. Identify Improvements
Document any potential improvements discovered during evaluation:
- Performance optimizations
- Additional industries to support
- Edge cases not covered
- Documentation updates needed

### 5. User Approval (REQUIRED)
**STOP and ask the user before committing.**

## Expected Impact

**Before HRV-12**:
- Farfetch precision: 40%
- All keywords have uniform weight
- Industry context ignored

**After HRV-12**:
- Farfetch precision: 45-55% (target)
- E-commerce keywords boosted for e-commerce filings
- SaaS keywords boosted for SaaS filings
- Reduced cross-industry false positives

## Reference

- **Issue source**: HRV-6 Validation Analysis, Section 4 (Industry-Specific Insights)
- **Dependencies**: HRV-9 (complete), HRV-4 (analysis complete)
- **Related**: HRV-15 (will regenerate candidates after this), HRV-16 (validation)

---

**Last Updated**: 2026-01-03
**Format Version**: 2.6

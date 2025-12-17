# WORKER PROMPT: Task GI-6 - Calibrate Richness Formula Weights

```
===============================================================================
TASK ID:       GI-6
TASK NAME:     Calibrate richness formula weights based on GI-3 analysis
WORKSTREAM:    Goldmine Improvement
SOURCE:        docs/GOLDMINE_1_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours (analysis review 30 min, implementation 60 min, testing 90 min)
RISK LEVEL:    Medium (changes score distribution affecting downstream goldmine detection)
PARALLEL WITH: None
===============================================================================
```

## Objective

Adjust richness formula weights in `_compute_richness_score()` based on GI-3 analysis findings to produce a more meaningful score distribution where high-quality segments can reach the 8.0+ tier.

**Business Rationale**: GI-3 analysis revealed critical bottlenecks: maximum observed score is 7.00 (never reaching 8.0+), 56% of segments score below 2.0, and the cohort bonus (+1.5) was never applied (now fixed by GI-4). With cohort detection now working, formula weights need calibration to utilize the full 0-10 scale and create meaningful tier separation.

**Current Behavior**:
- Max observed score: 7.00 (Farfetch)
- 0 segments in high-value tier (≥8.0)
- Slack average: 2.28 (should be ~4.5+ given its excellent disclosure)
- No retention metric keyword bonus
- No usage metric keyword bonus
- With GI-4 cohort fixes, top segments could now reach ~8.35

**Desired Behavior**:
- Top 5% of segments score ≥8.0 (high-value tier populated)
- Clear tier separation: goldmine (6.0-7.99) vs high-value (8.0+)
- Slack segments with NRR/cohort content score ≥7.0
- Formula rewards retention and usage metrics as identified in GI-3

## Prerequisites

- ✅ GI-3 complete (distribution analysis with 4 specific weight recommendations)
- ✅ GI-4 complete (cohort detection patterns - cohort bonus now triggers)
- Optional: GI-5 (SaaS patterns - provides additional +0.5 bonus)

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Modify `_compute_richness_score()` method to implement GI-3 weight recommendations

## Files to Create

1. **`tests/unit/extraction/test_segment_enricher_richness.py`** - Focused unit tests for richness formula calibration

## Files to Read (Context Only)

- `docs/analysis/GI-3_richness_distribution.md` - Contains the 4 weight adjustment recommendations
- `docs/analysis/GI-2_slack_ground_truth.md` - Ground truth for validating improvements
- `src/extraction/segment_enricher.py` - Current formula implementation (lines 526-571)

## Implementation Requirements

### Core Formula Changes

Based on GI-3 analysis, implement the following weight adjustments:

1. **Add Retention Metric Keyword Bonus (+1.0)**

   GI-3 Recommendation 1: Add explicit bonus for retention-related keywords.

   - Add class attribute `RETENTION_KEYWORDS` with patterns:
     - `"net dollar retention"` (case-insensitive)
     - `"dollar-based retention"`
     - `"ndr"` or `"ndrr"` (acronyms, word boundaries)
     - `"gross retention"`
   - Add `_detect_retention_keywords()` method returning bool
   - In `_compute_richness_score()`: +1.0 if retention keywords detected
   - **Rationale**: GI-1 found 87 retention-related snippets. GI-2 shows NRR segments score 5.0-5.55 but should be 6.5+. Slack's famous 143% NRR disclosure should be a goldmine.

2. **Add Usage Metric Keyword Bonus (+0.5)**

   GI-3 Recommendation 4: Add bonus for DAU/MAU/engagement metrics.

   - Add class attribute `USAGE_KEYWORDS` with patterns:
     - `"daily active users"` or `"DAU"`
     - `"monthly active users"` or `"MAU"`
     - `"weekly active users"` or `"WAU"`
     - `"active users"` (generic)
   - Add `_detect_usage_keywords()` method returning bool
   - In `_compute_richness_score()`: +0.5 if usage keywords detected
   - **Rationale**: GI-2 shows Slack's "10 million daily active users" segment scores 3.90 but should be ~4.5+.

3. **Enhance Definition Bonus with Metric Context (+0.5 conditional)**

   GI-3 Recommendation 3: Increase definition bonus when combined with metrics.

   - Current: +1.0 for `contains_definition_flag`
   - New: +1.5 if `(contains_definition_flag AND distinct_metric_count >= 2)`
   - Keep: +1.0 if `(contains_definition_flag AND distinct_metric_count < 2)`
   - **Rationale**: GI-2 shows definitions combined with metrics (e.g., DAU definition with 10M value) score only 3.90. These are high-value disclosures.

4. **Add Combination Bonus (+0.5)**

   Reward segments with multiple high-value signals.

   - +0.5 if BOTH `contains_temporal_trend` AND `contains_cohort_breakdown`
   - **Rationale**: Segments with both time series and cohort analysis are exceptionally valuable (e.g., NRR trends by cohort year). This rewards the intersection without double-counting.

### Updated Formula Summary

After changes, the formula should be:

```
Score = Base confidence (0-3.0)
      + Metric density (0-2.0)
      + Temporal bonus (0 or 1.0)
      + Cohort bonus (0 or 1.5)
      + Definition bonus (0 or 1.0, or 1.5 if metrics≥2)
      + Retention keyword bonus (0 or 1.0)  [NEW]
      + Usage keyword bonus (0 or 0.5)      [NEW]
      + Combination bonus (0 or 0.5)        [NEW]
      + Image bonus (0-1.5)
      + SaaS indicator bonus (0 or 0.5)     [FROM GI-5, if complete]

Capped at 10.0
```

**New theoretical maximum**: 3.0 + 2.0 + 1.0 + 1.5 + 1.5 + 1.0 + 0.5 + 0.5 + 1.5 + 0.5 = 13.0 → capped to 10.0

### Constants to Consider

- Keep `GOLDMINE_THRESHOLD = 6.0` (the standard threshold)
- Consider adding `HIGH_VALUE_THRESHOLD = 8.0` constant for clarity
- Document threshold rationale in comments

### Error Handling

- All keyword detection methods should handle None/empty text gracefully
- No exceptions should propagate from keyword matching
- Return 0.0 bonus if detection fails

## Test Requirements

### Coverage Target: ≥95% for `_compute_richness_score()` and new detection methods

### Test Categories (25+ tests recommended)

1. **Component Isolation Tests** (8+ tests)
   - Test each component in isolation with others zeroed out:
     - Confidence only → verify 0-3.0 range
     - Metric count only → verify 0-2.0 cap
     - Temporal only → verify +1.0
     - Cohort only → verify +1.5
     - Definition only (no metrics) → verify +1.0
     - Definition with metrics≥2 → verify +1.5
     - Retention keywords → verify +1.0
     - Usage keywords → verify +0.5

2. **Combination Tests** (5+ tests)
   - Temporal + cohort → verify +0.5 combination bonus (total +3.0)
   - All flags true, max metrics → verify approaches 10.0
   - No flags/metrics → verify minimal score (just confidence)
   - Retention + cohort + temporal → verify all bonuses stack
   - Definition + metrics + retention → verify complex combination

3. **Boundary Tests** (4+ tests)
   - Score exactly at 6.0 threshold (goldmine cutoff)
   - Score exactly at 8.0 threshold (high-value cutoff)
   - Maximum possible score → verify 10.0 cap
   - Minimum possible score (all zeros)

4. **Keyword Detection Tests** (8+ tests)
   - Retention keywords:
     - `"Net Dollar Retention Rate was 143%"` → True
     - `"Our NDRR exceeded 130%"` → True
     - `"gross retention rate"` → True
     - `"customer retention"` → False (too generic, covered by cohort)
   - Usage keywords:
     - `"10 million daily active users"` → True
     - `"DAU increased 50%"` → True
     - `"monthly active users grew"` → True
     - `"active customers"` → False (not "active users")

5. **Regression Tests** (3+ tests)
   - Farfetch top segment still scores ≥7.0
   - Slack top segment now scores higher than before
   - Basic segments without special flags still score correctly

6. **Real S-1 Scenarios** (3+ tests)
   - Slack NRR segment (87% retention language) → should score ≥7.0
   - Slack DAU segment → should score ≥4.5
   - Slack cohort + NRR + temporal combined → should score ≥8.0

### Known Edge Cases to Test

- Empty text in segment
- Multiple retention keywords in same segment (should be +1.0, not stacked)
- Overlapping patterns (e.g., "net dollar retention rate" matches both patterns)
- Very high confidence (1.0) + all bonuses → verify cap at 10.0

## Acceptance Criteria

- [ ] **Retention keyword detection** implemented with `RETENTION_KEYWORDS` and `_detect_retention_keywords()`
- [ ] **Usage keyword detection** implemented with `USAGE_KEYWORDS` and `_detect_usage_keywords()`
- [ ] **Enhanced definition bonus** (+1.5 when combined with metrics≥2)
- [ ] **Combination bonus** (+0.5 for temporal AND cohort)
- [ ] **Formula still capped at 10.0**
- [ ] **25+ unit tests** in `tests/unit/extraction/test_segment_enricher_richness.py`
- [ ] Test coverage ≥95% for `_compute_richness_score()` and new detection methods
- [ ] All existing tests in `tests/unit/extraction/` still pass
- [ ] `mypy src/extraction/segment_enricher.py --strict` passes
- [ ] **Slack top segment scores higher** than baseline 6.85 (target: ≥8.0 with cohort bonus)
- [ ] At least one segment in test suite reaches 8.0+ (high-value tier no longer empty)
- [ ] Formula docstring updated to document new components

## Do NOT

- Change `COHORT_PATTERNS` (GI-4 already completed)
- Change `SAAS_PATTERNS` (GI-5's scope)
- Remove or reduce existing bonuses (additive changes only)
- Change detection methods for temporal/cohort/definition flags
- Modify database schema
- Add new database fields (use existing `richness_score`)
- Change `GOLDMINE_THRESHOLD` without documenting rationale

## Verification Commands

```bash
# Run new richness formula tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher_richness.py -v

# Check coverage for richness method
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher_richness.py \
  --cov=src/extraction/segment_enricher --cov-report=term-missing

# Type safety check
mypy src/extraction/segment_enricher.py --strict

# Run ALL segment_enricher tests (regression check)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher*.py -v --tb=short

# Verify formula produces expected scores for test cases
python3 << 'EOF'
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment

enricher = SegmentEnricher()

# Test case: High-value segment with NRR + cohort + temporal
segment = SourceSegment(
    filing_id=35,
    sequence_index=1,
    raw_html="<p>Net Dollar Retention Rate was 143% for the fiscal year 2018 cohort, growing from 152% in 2017.</p>",
    classifier_confidence=0.95,
    distinct_metric_count=2,
    contains_temporal_trend=True,
    contains_cohort_breakdown=True,  # Now detected by GI-4
    contains_definition_flag=False,
    image_count=0,
)

# Manual enrichment to test formula
score = enricher._compute_richness_score(segment)
print(f"NRR + cohort + temporal segment: {score}")
print(f"Target: >= 8.0, Achieved: {score >= 8.0}")
EOF
```

## Expected Impact

**Before GI-6**:
- Max observed score: 7.00
- 0 segments in high-value tier (≥8.0)
- Slack average: 2.28
- No recognition of retention/usage metrics

**After GI-6** (combined with GI-4 cohort fixes):
- Top Slack segments: ~8.0+ (with cohort bonus triggering)
- High-value tier populated with truly exceptional segments
- Retention metrics like NRR get appropriate recognition
- Usage metrics (DAU/MAU) get modest bonus
- Clear tier separation enables meaningful prioritization

**Score Increase Examples**:
| Segment Type | Before | After | Change |
|--------------|--------|-------|--------|
| Slack NRR disclosure | 5.55 | ~7.55 | +2.0 (cohort +1.5, retention +1.0, combo -0.5 overlap) |
| Slack DAU definition | 3.90 | ~5.40 | +1.5 (usage +0.5, def+metrics +0.5, maybe cohort +1.5) |
| Farfetch top segment | 7.00 | ~8.50 | +1.5 (cohort bonus now triggers) |

## Documentation Updates

After completing implementation:

1. **Update `docs/GOLDMINE_1_IMPROVEMENT_PLAN.md`**:
   - Change GI-6 status from `🟡 PENDING` to `✅ COMPLETE (YYYY-MM-DD)`
   - Add actual time taken
   - Add completion notes summarizing weight changes

2. **Update `src/extraction/segment_enricher.py` docstring**:
   - Update `_compute_richness_score()` docstring to reflect new formula components

3. **Archive this worker prompt**:
   - Move `docs/WORKER_PROMPT_TASK_GI-6.md` to `docs/archive/WORKER_PROMPT_TASK_GI-6.md`

## Git Instructions

After all tests pass and acceptance criteria are met:

```bash
# Stage changes
git add src/extraction/segment_enricher.py
git add tests/unit/extraction/test_segment_enricher_richness.py
git add docs/GOLDMINE_1_IMPROVEMENT_PLAN.md

# Commit with descriptive message
git commit -m "$(cat <<'EOF'
GI-6: Calibrate richness formula weights based on GI-3 analysis

Implement 4 weight recommendations from GI-3 distribution analysis:
1. Add retention keyword bonus (+1.0) for NRR/NDRR/gross retention
2. Add usage keyword bonus (+0.5) for DAU/MAU/WAU metrics
3. Enhance definition bonus (+1.5 when combined with metrics>=2)
4. Add combination bonus (+0.5 for temporal AND cohort together)

With GI-4 cohort detection fixes and these calibrations:
- High-value tier (8.0+) is now achievable
- Slack NRR segments properly recognized as high-value
- DAU/MAU usage metrics receive appropriate recognition
- Formula utilizes full 0-10 scale

Based on GI-3 analysis of 340 segments across 6 validation filings.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"

# Push to remote
git push origin main
```

## Reference

- **Issue source**: docs/GOLDMINE_1_IMPROVEMENT_PLAN.md, GI-6
- **Analysis basis**: docs/analysis/GI-3_richness_distribution.md (4 specific recommendations)
- **Ground truth**: docs/analysis/GI-2_slack_ground_truth.md (25 goldmines, 4% current recall)
- **Dependencies**: GI-3 (analysis), GI-4 (cohort patterns working)
- **Enables**: GI-7 (high-value metric bonuses), GI-8 (validation)

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)

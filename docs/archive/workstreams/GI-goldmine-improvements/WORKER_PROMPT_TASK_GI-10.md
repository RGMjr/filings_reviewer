# WORKER PROMPT: Task GI-10 - Usage Metric Boost

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GI-10
TASK NAME:     Implement tiered usage metric bonus for enhanced DAU/MAU/WAU scoring
WORKSTREAM:    Goldmine Improvement
SOURCE:        GOLDMINE_1_IMPROVEMENT_PLAN.md (Phase 5)
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-2 hours (analysis 20 min, implementation 40 min, testing 45 min)
RISK LEVEL:    Low (additive enhancement to existing patterns)
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Upgrade the flat +0.5 usage metric bonus (GI-6) to a tiered bonus system, similar to the GI-9 definition bonus enhancement. This will properly reward segments containing rich usage metric disclosures (DAU/MAU/WAU with counts, definitions, or trends).

**Business Rationale**: GI-3 analysis showed Slack's "10 million daily active users" segment scored only 3.90 (GT #10 in GI-2). Usage metrics are core customer metrics that deserve stronger scoring when combined with numeric values or definitions. The flat +0.5 bonus does not differentiate between a passing mention of "active users" and a detailed disclosure like "We had 10 million daily active users as of January 31, 2019."

**Current Behavior**: All usage metric matches receive +0.5, regardless of context quality. Segments with usage counts score the same as segments with just a keyword mention.

**Desired Behavior**: Tiered bonuses that reward richer usage disclosures:
- +1.0 for usage metric with numeric value (e.g., "10 million daily active users")
- +0.75 for usage metric definition (e.g., "We define DAU as...")
- +0.5 for basic usage keyword match (current behavior, fallback)

## Prerequisites

- GI-9 complete (provides the tiered bonus pattern to follow)
- `USAGE_KEYWORDS` patterns already implemented (GI-6)
- `_detect_usage_keywords()` method exists

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add tiered usage bonus logic, new patterns, and helper method
2. **`tests/unit/extraction/test_segment_enricher_richness.py`** - Add tests for tiered usage bonus (or create new test file if preferred)

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` - Review `_detect_usage_keywords()` (lines 627-660), `USAGE_KEYWORDS` (lines 212-227), and GI-9's tiered definition bonus implementation (lines 886-899)
- `docs/analysis/GI-3_richness_distribution.md` - Recommendation #4 (usage bonus rationale)
- `docs/analysis/GI-2_slack_ground_truth.md` - GT #10 showing DAU segment underscoring

## Implementation Requirements

### Core Functionality

1. **Add `USAGE_WITH_COUNT_PATTERNS` class attribute**
   - Pattern: DAU/MAU/WAU with numeric value (e.g., "10 million daily active users", "5M MAU")
   - Pattern: Active users with percentage change (e.g., "daily active users grew 50%")
   - Pattern: Numeric + "active users" (e.g., "600,000 organizations with daily active users")
   - Should be more specific than base `USAGE_KEYWORDS` to avoid false positives

2. **Add `_detect_usage_with_count()` method**
   - Returns True if segment text matches any `USAGE_WITH_COUNT_PATTERNS`
   - Similar structure to `_detect_usage_keywords()` but with stricter patterns
   - Store result in `extra_metadata["contains_usage_with_count"]`

3. **Modify `_detect_usage_keywords()` return value**
   - In addition to setting `contains_usage_keywords`, also set `contains_usage_with_count` if the stricter patterns match
   - Alternatively, call `_detect_usage_with_count()` separately in `_enrich_segment()`

4. **Update `_compute_richness_score()` to use tiered bonus**
   - Replace flat +0.5 with tiered logic:
     ```
     if contains_usage_with_count:
         score += 1.0  # Usage metric with numeric value
     elif contains_usage_keywords AND (contains_definition_flag OR metric_count >= 1):
         score += 0.75  # Usage metric with definition or metric context
     elif contains_usage_keywords:
         score += 0.5  # Basic usage keyword (current behavior)
     ```
   - Ensure tiers are mutually exclusive (highest tier wins)

5. **Update docstring for `_compute_richness_score()`**
   - Document the tiered usage bonus
   - Update the formula description

### Error Handling

- If `extra_metadata` is None or missing keys, default to False (no bonus)
- All patterns should be compiled at class level (no runtime compilation)
- Handle empty/None text gracefully (return False)

### Performance Requirements

- New patterns must use non-backtracking regex
- Compilation at class level to avoid per-call overhead
- No measurable impact on enrichment throughput

## Test Requirements

### Coverage Target: ≥95% for `_detect_usage_with_count()` and tiered usage bonus logic

### Test Categories (20+ tests recommended)

1. **Usage With Count Detection** (8-10 tests)
   - "10 million daily active users" → True
   - "5M MAU" → True
   - "daily active users grew 50%" → True
   - "600,000 organizations with daily active users" → True
   - "more than 10 million daily active users" → True
   - "DAU of 8.5 million" → True
   - "our active users" (no count) → False
   - "daily active users" (no count) → False

2. **Tiered Bonus Calculation** (6-8 tests)
   - Usage with count → +1.0 (not +0.5 or +0.75)
   - Usage keyword + definition flag → +0.75
   - Usage keyword + metric_count >= 1 → +0.75
   - Basic usage keyword only → +0.5
   - No usage keyword → +0.0
   - Tiers are mutually exclusive (highest wins)

3. **Integration with Full Score** (4-6 tests)
   - Segment with usage count + temporal + definition should score higher
   - Verify total score includes correct tiered bonus
   - Real Slack S-1 snippet: "10 million daily active users" segment

4. **Edge Cases** (2-3 tests)
   - Empty text
   - None extra_metadata
   - Segment with both usage patterns (should only count once at highest tier)

### Known Edge Cases to Test

- "daily active users" without a number (should NOT match count pattern)
- "DAU" alone (base match only)
- Numbers in different formats: "10 million", "10M", "10,000,000"
- Percentage growth: "grew 50%" vs just mentioning "50%"

## Acceptance Criteria

- [ ] `USAGE_WITH_COUNT_PATTERNS` class attribute added with 4+ patterns
- [ ] `_detect_usage_with_count()` method implemented and integrated
- [ ] `_compute_richness_score()` uses tiered usage bonus (+1.0 / +0.75 / +0.5)
- [ ] Docstring updated to document tiered bonus
- [ ] **20+ unit tests** for usage detection and tiered bonus
- [ ] **Test coverage ≥95%** for new methods
- [ ] All new tests pass
- [ ] All existing tests still pass (no regression)
- [ ] `mypy src/extraction/segment_enricher.py --strict` passes
- [ ] Slack's "10 million daily active users" segment scores higher than before (verify with quick test)

## Do NOT

- Remove existing `USAGE_KEYWORDS` patterns (tiered bonus builds on them)
- Change the base +0.5 bonus for simple keyword matches (preserve backward compatibility)
- Modify cohort detection or retention bonus logic (separate concerns)
- Add patterns that overlap with `RETENTION_KEYWORDS` (e.g., avoid "retention" in usage patterns)
- Change `GOLDMINE_THRESHOLD` or `HIGH_VALUE_THRESHOLD` (out of scope)

## Verification Commands

```bash
# Run all segment_enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher*.py -v

# Check coverage for segment_enricher
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher*.py \
  --cov=src/extraction/segment_enricher --cov-report=term-missing

# Type safety check
mypy src/extraction/segment_enricher.py --strict

# Quick validation of Slack improvement (optional, requires database)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -c "
# Verify the DAU segment would score higher with new logic
from src.extraction.segment_enricher import SegmentEnricher
enricher = SegmentEnricher()
result = enricher._detect_usage_with_count('As of January 31, 2019, Slack had more than 10 million daily active users')
print(f'Usage with count detected: {result}')
"

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q
```

## Expected Impact

**Before GI-10**:
- Slack "10 million daily active users" segment: +0.5 usage bonus
- All usage mentions treated equally regardless of numeric context

**After GI-10**:
- Slack "10 million daily active users" segment: +1.0 usage bonus (+0.5 increase)
- Usage definitions with metric context: +0.75 bonus
- Basic mentions: +0.5 bonus (preserved)

**Score Impact Example** (Slack GT #10 - DAU definition):
- Before: 3.90 (with +0.5 usage bonus)
- After: ~4.40 (with +1.0 usage with count bonus)
- Moves closer to 6.0 goldmine threshold

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# Example showing the tiered pattern - NOT meant to be copied directly

USAGE_WITH_COUNT_PATTERNS: List[Pattern[str]] = [
    # DAU/MAU/WAU with numeric prefix
    re.compile(
        r"\b\d+(?:\.\d+)?\s*(?:million|billion|M|B|K)?\s+(?:daily|monthly|weekly)\s+active\s+users?\b",
        re.IGNORECASE,
    ),
    # ... additional patterns
]

def _detect_usage_with_count(self, text: str) -> bool:
    """Check for usage metrics with numeric values."""
    if not text:
        return False
    return any(p.search(text) for p in self.USAGE_WITH_COUNT_PATTERNS)

# In _compute_richness_score:
if extra_metadata.get("contains_usage_with_count"):
    score += 1.0
elif extra_metadata.get("contains_usage_keywords"):
    if segment.contains_definition_flag or metric_count >= 1:
        score += 0.75
    else:
        score += 0.5
```
</details>

## Reference

- **Issue source**: GOLDMINE_1_IMPROVEMENT_PLAN.md, Phase 5, Task GI-10
- **Dependencies**: GI-9 (tiered bonus pattern), GI-6 (base usage keywords)
- **Related**: GI-2 (Slack ground truth GT #10), GI-3 (Recommendation #4)

## Post-Implementation Tasks

After completing this task:

1. **Update GOLDMINE_1_IMPROVEMENT_PLAN.md**:
   - Mark GI-10 as ✅ COMPLETE with date
   - Add completion notes summarizing patterns added and test count
   - Update Version History

2. **Commit and push**:
   ```bash
   git add src/extraction/segment_enricher.py tests/unit/extraction/test_segment_enricher*.py docs/GOLDMINE_1_IMPROVEMENT_PLAN.md
   git commit -m "GI-10: Add tiered usage metric bonus for DAU/MAU/WAU scoring

   - Add USAGE_WITH_COUNT_PATTERNS for numeric usage metrics
   - Implement _detect_usage_with_count() method
   - Upgrade flat +0.5 to tiered bonus: +1.0 (count), +0.75 (context), +0.5 (basic)
   - Add [N] unit tests for tiered usage bonus

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>"

   git push origin main
   ```

3. **Optional - Re-run validation** to measure impact:
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python3 scripts/rerun_goldmine_validation.py --no-llm
   ```

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (requirements-focused)

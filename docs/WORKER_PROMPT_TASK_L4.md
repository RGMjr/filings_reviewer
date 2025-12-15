# WORKER PROMPT: Task L4 - Post-Value Keyword Distance Multiplier

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       L4
TASK NAME:     Apply distance multiplier to prefer pre-value keywords
WORKSTREAM:    Metric Logic Repairs (L-series)
SOURCE:        METRIC_IDENTIFICATION_ISSUES.md Issue 5
STATUS:        🟡 PENDING
TIME ESTIMATE: 1-1.5 hours
PARALLEL WITH: None (requires L3 complete)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Apply a 0.9x distance multiplier to post-value keywords to prefer pre-value keywords when distances are similar.

**Business Rationale**: In SEC filings, metrics typically appear BEFORE their values:
- ✅ "**Net Revenue** of $1.2 million" ← keyword BEFORE value (preferred)
- ⚠️ "$1.2 million in **Net Revenue**" ← keyword AFTER value (acceptable but less common)

When two keywords are equidistant from a number, the pre-value keyword should win.

## Prerequisites

- **L3 MUST be complete** (keyword direction detection implemented)
- Verify `keyword_matching.py` has `direction` field in `KeywordMatch` results
- Check that `direction` values are: `"before"`, `"after"`, or `"at"`

## Files to Modify

1. **`src/review/config.py`** - Add `post_value_distance_multiplier` config parameter
2. **`src/review/keyword_matching.py`** - Apply multiplier in distance sorting logic
3. **`tests/unit/review/test_keyword_matching.py`** - Add test cases for multiplier behavior

## Implementation Requirements

### Core Functionality

1. **Configuration Parameter**
   - Add `post_value_distance_multiplier: float = 0.9` to `CandidateGenerationConfig` dataclass
   - Default value: 0.9 (10% preference for pre-value keywords)
   - Valid range: 0.5 - 1.0 (values < 0.9 = stronger preference for "before")
   - Document rationale in config docstring

2. **Distance Sorting Logic**
   - When sorting keyword matches by distance, compute `effective_distance` to penalize post-value keywords
   - Sort by `effective_distance` (ascending - lower is better)
   - **Important**: Store original `raw_distance` in match results (don't modify stored distance)

3. **Implementation Approach**

   **Goal**: PRE-value keywords should win ties or near-ties

   **Method**: Penalize post-value keywords by INCREASING their effective distance

   ```python
   # In keyword_matching.py
   effective_distance = raw_distance
   if keyword_match.direction == "after":
       # Penalize post-value keywords by dividing (increases effective distance)
       effective_distance = raw_distance / config.post_value_distance_multiplier
   # Sort by effective_distance (ascending)
   ```

   **Example with multiplier = 0.9**:
   - "before" keyword at 50 chars → effective distance = 50
   - "after" keyword at 50 chars → effective distance = 50 / 0.9 = 55.6 (penalized)
   - "before" wins (lower effective distance)

   **Why divide?** A multiplier < 1.0 means we want to penalize. Dividing by 0.9 increases the distance (penalty). Multiplying by 0.9 would decrease distance (reward), which is backwards.

4. **Tiebreaking Behavior**
   - When keywords are nearly equidistant:
     - Pre-value needs ~11% advantage to overcome equal distance (with default 0.9 multiplier)
     - Example: before=50, after=45 → both effective=50 (tie)
     - Example: before=49, after=45 → before wins (49 < 50)

### Error Handling

- **Invalid multiplier values**: Clamp to range [0.5, 1.0] with warning log
- **Missing direction field**: Treat as `"before"` (no penalty) with debug log
- **No exceptions should propagate** from multiplier logic

### Performance Requirements

- Multiplier application should add negligible overhead (<1% to keyword matching)
- No additional regex or string operations required

## Test Requirements

### Coverage Target: **Maintain ≥ 90%** for `keyword_matching.py`

### Test Cases (6+ new tests recommended)

1. **TestPostValueMultiplier** (new test class)

   ```python
   def test_before_keyword_preferred_at_equal_distance(self):
       """When keywords are equidistant, pre-value (before) wins."""
       text = "revenue was 100 of revenue"  # 'revenue' appears before AND after '100'
       # Should prefer the first 'revenue' (before the number)

   def test_after_keyword_wins_when_significantly_closer(self):
       """Post-value keyword wins if much closer despite penalty."""
       text = "revenue ... (50 chars) ... 100 margin"  # 'margin' much closer
       # 'margin' is post-value but significantly closer, should still win

   def test_multiplier_value_configurable(self):
       """Custom multiplier values change outcomes."""
       config = CandidateGenerationConfig(post_value_distance_multiplier=0.8)
       # Stronger penalty (0.8 vs 0.9) should change tiebreaking

   def test_multiplier_at_boundaries(self):
       """Test at exact tiebreak threshold."""
       # If before=50 and after=45, with multiplier=0.9:
       # - before effective = 50
       # - after effective = 45/0.9 = 50
       # Should be exact tie (may need secondary tiebreaker)

   def test_direction_missing_defaults_to_no_penalty(self):
       """If direction field missing, treat as 'before' (no penalty)."""
       # Test backward compatibility with pre-L3 code

   def test_multiplier_clamping(self):
       """Invalid multiplier values (e.g., 2.0, 0.0) are clamped."""
       config = CandidateGenerationConfig(post_value_distance_multiplier=2.0)
       # Should clamp to 1.0 and log warning
   ```

### Integration Tests

Add tests in `test_candidate_generator.py` to verify end-to-end behavior:
- Candidate with post-value keyword at equal distance should lose to pre-value
- Verify `distance` field in candidate still stores original (unmodified) distance

## Acceptance Criteria

- [ ] `post_value_distance_multiplier` added to `CandidateGenerationConfig` (default: 0.9)
- [ ] Keyword sorting applies multiplier to "after" direction matches (divides to penalize)
- [ ] Original (unmodified) distance still stored in `KeywordMatch` results
- [ ] Config parameter has docstring explaining rationale
- [ ] **6+ unit tests** covering edge cases (equal distance, significantly closer, configurable)
- [ ] **Test coverage ≥ 90%** maintained for `keyword_matching.py`
- [ ] All existing tests still pass (`pytest tests/unit/review/test_keyword_matching.py -v`)
- [ ] `mypy src/review/keyword_matching.py --strict` passes
- [ ] `mypy src/review/config.py --strict` passes

## Do NOT

- Modify `false_positive_filter.py` (different responsibility)
- Modify `candidate_generator.py` orchestration logic (uses config automatically)
- Add new module files (L4 is an enhancement to existing modules)
- Change the signature of public functions (maintain backward compatibility)
- Modify stored distance values (only effective_distance for sorting)

## Verification Commands

```bash
# Run targeted tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py::TestPostValueMultiplier -v

# Check coverage maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_keyword_matching.py \
  --cov=src/review/keyword_matching --cov-report=term-missing

# Type check both modified files
mypy src/review/keyword_matching.py --strict
mypy src/review/config.py --strict

# Full review module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --no-cov -q
```

## Example Implementation Reference

**Note**: Design your own solution - this is for reference only.

<details>
<summary>Expand to see example structure</summary>

```python
# In src/review/config.py
@dataclass
class CandidateGenerationConfig:
    """Configuration for candidate generation."""
    # ... existing fields ...

    post_value_distance_multiplier: float = 0.9
    """
    Multiplier for post-value (after) keyword distances to prefer pre-value keywords.

    When two keywords are equidistant from a number, SEC filings typically show
    the metric name BEFORE the value (e.g., "Net Revenue of $1.2M"). This multiplier
    penalizes post-value keywords by dividing their distance, making pre-value keywords
    preferred in tiebreak scenarios.

    Value range: 0.5 - 1.0
    - 0.9 (default): Mild preference for pre-value (11% effective penalty)
    - 0.8: Strong preference for pre-value (25% effective penalty)
    - 1.0: No preference (equal treatment)
    """

# In src/review/keyword_matching.py
def _calculate_effective_distance(match: KeywordMatch,
                                  config: CandidateGenerationConfig) -> float:
    """Calculate effective distance for sorting, applying post-value penalty."""
    distance = match.distance

    if match.direction == "after":
        # Penalize post-value keywords (increases effective distance)
        multiplier = max(0.5, min(1.0, config.post_value_distance_multiplier))
        return distance / multiplier

    return distance

def find_closest_keywords(text: str,
                          number_pos: int,
                          config: CandidateGenerationConfig) -> List[KeywordMatch]:
    """Find closest keywords to number, preferring pre-value keywords."""
    # ... find all keyword matches ...

    # Sort by effective distance (with post-value penalty applied)
    matches.sort(key=lambda m: _calculate_effective_distance(m, config))

    return matches
```
</details>

## Reference

- **Issue source**: `METRIC_IDENTIFICATION_ISSUES.md` Issue 5
- **Dependency**: L3 (keyword direction detection) must be complete
- **Related**: L1 (respectively parser), L2 (false positive filter)

---

**Last Updated**: 2025-12-15
**Format Version**: 2.0 (concise requirements-focused format)
```

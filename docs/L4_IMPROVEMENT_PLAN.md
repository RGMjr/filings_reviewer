# L4 Improvement Plan: Post-Value Keyword Distance Multiplier Enhancements

**Plan Version**: 1.0
**Created**: 2025-12-15
**Status**: Ready for Implementation
**Prerequisites**: L3 complete ✅, L4 basic implementation complete ✅

---

## Overview

This plan addresses critical issues and quality improvements for the L4 post-value keyword distance multiplier feature. The current implementation is functional but has design issues that affect correctness and quality.

**See Also**: `docs/L4_CRITICAL_EVALUATION.md` for full analysis

---

## Workstream Breakdown

### Workstream A: Business Rationale Resolution (P0 - CRITICAL)

**Objective**: Resolve contradiction between L4 spec (prefer pre-value) and Issue 5 (prefer post-value)

**Status**: ⏸️ Requires User Input

#### Task A1: User Consultation on Business Logic

**Goal**: Clarify which keyword direction preference is correct

**Questions for User**:

1. **Primary Pattern in SEC Filings**: Which pattern is more common?
   - A: "**Gross margin** of 33%" (metric before value)
   - B: "Achieved 33% **gross margin**" (metric after value)

2. **Preference in Ambiguous Cases**: When both patterns exist, which should win?
   - A: Prefer pre-value (L4 current behavior)
   - B: Prefer post-value (Issue 5 suggestion)
   - C: Context-dependent (bullets vs sentences)

3. **Acceptable Tradeoffs**: Which false positives are worse?
   - A: Matching value to heading keyword (pre-value contamination)
   - B: Matching value to distant clarification (post-value miss)

**Deliverable**: Decision on one of three options:
- **Option A**: Keep current (prefer pre-value)
- **Option B**: Reverse logic (prefer post-value)
- **Option C**: Context-dependent (recommended)

**Estimated Time**: 30-minute discussion + 15-minute decision documentation

**Dependencies**: None

**Blocking**: Tasks A2, A3 (can't implement until decision made)

---

#### Task A2: Implement Chosen Business Logic

**Prerequisite**: Task A1 complete

**Implementation Varies by Option:**

**If Option A (Keep Current)**:
- ✅ No code changes needed
- Update documentation to justify choice
- Add comments explaining why Issue 5 was not adopted
- **Effort**: 30 minutes (documentation only)

**If Option B (Reverse Logic)**:
- Change multiplier application from division to multiplication
- Update all tests to expect post-value preference
- Update config comments and documentation
- **Effort**: 2 hours (code + tests + docs)

**If Option C (Context-Dependent) - RECOMMENDED**:
- Implement pattern detection for different contexts
- Apply pre-value preference in some contexts, post-value in others
- See detailed spec in Task A3
- **Effort**: 3-4 hours (new logic + tests + docs)

---

#### Task A3: Context-Dependent Logic Specification (IF OPTION C)

**Goal**: Define rules for when to prefer pre-value vs post-value keywords

**Proposed Rules**:

| Context | Preference | Multiplier | Rationale |
|---------|------------|------------|-----------|
| Bullet points / lists | Pre-value | 0.9 (penalize post) | Metrics typically in subject position |
| Parenthetical text `(...)` | Post-value | 1.1 (boost post) | Clarifications appear after values |
| Sentences with "is/was/were" | Pre-value | 0.9 (penalize post) | Subject-verb structure |
| Sentences with "of/for" | Post-value | 1.1 (boost post) | Object position after value |
| Table cells | Pre-value | 0.85 (strong penalty) | Headers above/before data |
| Appositive constructions | Post-value | 1.15 (strong boost) | "33%, or gross margin, ..." |

**Detection Logic**:

```python
def get_direction_multiplier(
    self,
    text: str,
    number_position: int,
    keyword_position: int,
    boundaries: List[TextBoundary],
) -> float:
    """
    Determine direction multiplier based on context.

    Returns:
        Multiplier for effective distance calculation:
        - < 1.0: Penalize this direction
        - 1.0: No preference
        - > 1.0: Boost this direction (make more favorable)
    """
    # Detect context patterns
    is_bullet_point = self._in_bullet_point(number_position, boundaries)
    is_parenthetical = self._in_parentheses(number_position, text)
    is_table = self._in_table(number_position, boundaries)
    has_copula = self._has_copula_verb(text, number_position, keyword_position)
    has_preposition = self._has_preposition(text, number_position, keyword_position)

    # Apply rules
    if is_table:
        return 0.85  # Strong pre-value preference
    elif is_parenthetical:
        return 1.1   # Post-value preference
    elif is_bullet_point:
        return 0.9   # Pre-value preference
    elif has_copula:
        return 0.9   # Pre-value preference (subject before "is")
    elif has_preposition:
        return 1.1   # Post-value preference (object after "of")
    else:
        return self.post_value_distance_multiplier  # Default
```

**Files to Modify**:
1. `src/review/keyword_matching.py` - Add context detection methods
2. `src/review/config.py` - Add context-specific multiplier config
3. `tests/unit/review/test_keyword_matching.py` - Add context tests

**Estimated Effort**: 3-4 hours

**Test Cases Required**:
```python
def test_bullet_point_prefers_pre_value():
    """Bullet points prefer keywords before values."""

def test_parenthetical_prefers_post_value():
    """Parenthetical text prefers keywords after values."""

def test_table_strongly_prefers_pre_value():
    """Table cells strongly prefer column headers before values."""

def test_copula_verb_prefers_pre_value():
    """'X is Y' structure prefers pre-value keyword."""

def test_preposition_prefers_post_value():
    """'X of Y' structure prefers post-value keyword."""
```

---

### Workstream B: Ambiguity Logging Fix (P1 - HIGH)

**Objective**: Fix ambiguity logging to use effective distance instead of raw distance

**Status**: ⏭️ Ready to Implement

#### Task B1: Refactor Ambiguity Logging

**Problem**: Current code logs ambiguity based on raw distance, but sorting uses effective distance

**Solution**: Store effective distance and use for ambiguity detection

**Files to Modify**:
- `src/review/keyword_matching.py:341-377`

**Changes Required**:

```python
# Phase 3: Sort by effective distance and compute for ambiguity logging
if self.prefer_closest_keyword:
    # Compute effective distance for all candidates
    candidates_with_effective_distance = []
    for kw, raw_distance in candidates_with_distance:
        direction = self.calculate_keyword_direction(kw.start, number.start)
        effective_distance = (
            raw_distance / self.post_value_distance_multiplier
            if direction == "after"
            else float(raw_distance)
        )
        candidates_with_effective_distance.append(
            (kw, raw_distance, effective_distance)
        )

    # Sort by effective distance, then length
    candidates_with_effective_distance.sort(
        key=lambda x: (x[2], -len(x[0].keyword))
    )

    # Phase 4: Detect ambiguous matches using EFFECTIVE distance
    if self.log_ambiguous_matches and len(candidates_with_effective_distance) > 1:
        min_effective_distance = candidates_with_effective_distance[0][2]
        ambiguous_keywords = [
            kw.keyword
            for kw, raw_dist, eff_dist in candidates_with_effective_distance
            if abs(eff_dist - min_effective_distance) <= self.ambiguity_threshold
        ]

        if len(ambiguous_keywords) > 1:
            logger.info(
                f"Ambiguous match: {len(ambiguous_keywords)} keywords equally close "
                f"(effective distance) to number '{number.raw_text}' "
                f"at ~{min_effective_distance:.1f} chars: "
                f"{', '.join(repr(k) for k in ambiguous_keywords[:5])}"
            )

    # Continue with rest of logic using (kw, raw_distance, effective_distance) tuples
    ...
```

**Test Case**:
```python
def test_ambiguity_logging_uses_effective_distance():
    """Ambiguity logging should use effective distance, not raw distance."""
    # Pre-value at 100 chars (effective: 100)
    # Post-value at 100 chars (effective: 111.11 with multiplier=0.9)
    # Should NOT log as ambiguous (11-char effective distance difference)
    text = "..."
    # Capture logs and verify no ambiguity logged
```

**Estimated Effort**: 1 hour

---

### Workstream C: Test Coverage Expansion (P1 - HIGH)

**Objective**: Add missing tests to verify correctness and edge cases

**Status**: ⏭️ Ready to Implement

#### Task C1: Threshold Test

**Goal**: Verify exact math for when post-value wins despite penalty

**Test Case**:
```python
def test_post_value_wins_at_exact_threshold():
    """
    Post-value keyword wins when effective distance < pre-value distance.

    With multiplier = 0.9:
    - Pre-value at 100 chars (effective: 100)
    - Post-value at 89 chars (effective: 98.89)
    - Post-value should win (98.89 < 100)
    """
    matcher = KeywordMatcher(
        max_keyword_distance=200,
        prefer_closest_keyword=True,
        post_value_distance_multiplier=0.9,
    )

    # Construct text with precise positioning
    # "revenue" at position 0-7 (distance to "100" at 100: 100 chars)
    # "margin" at position 111-117 (distance to "100": 89 chars)
    # Effective distances: 100 vs 98.89 → margin wins
    text = "revenue" + " " * 92 + "100" + " " * 8 + "margin"

    all_keywords = matcher.find_all_keywords(text)
    number = NumberMatch(start=100, end=103, raw_text="100", value=Decimal("100"), unit="count")

    keywords = matcher.find_keywords_near_number(number, all_keywords)

    # Should select "margin" (post-value closer after multiplier)
    assert len(keywords) >= 1
    assert "margin" in keywords[0].keyword.lower()
    assert keywords[0].direction == "after"
```

**Estimated Effort**: 30 minutes

---

#### Task C2: Integration Test

**Goal**: Verify L4 multiplier affects end-to-end candidate generation

**Test Case** (in `tests/integration/test_e2_candidate_filtering.py`):
```python
class TestL4Multiplier:
    """Integration tests for L4 post-value distance multiplier."""

    def test_multiplier_affects_candidate_keyword_selection(self, db_session):
        """
        L4 multiplier changes which keyword is selected for candidates.

        Scenario:
        - Segment with pre-value and post-value keywords equidistant
        - With multiplier=0.9: pre-value wins
        - With multiplier=1.0: tie (may pick either)
        """
        # Create test segment with controlled text
        segment = create_test_segment(
            text="revenue figures show 100 margin improvement",
            segment_type="paragraph"
        )

        # Generate with default multiplier (0.9)
        config_default = CandidateGenerationConfig(post_value_distance_multiplier=0.9)
        gen_default = CandidateGenerator(config=config_default)
        candidates_default = gen_default.generate_for_filing(
            filing_id=1, company_id=1, segments=[segment], db=db_session
        )

        # Generate with neutral multiplier (1.0)
        config_neutral = CandidateGenerationConfig(post_value_distance_multiplier=1.0)
        gen_neutral = CandidateGenerator(config=config_neutral)
        candidates_neutral = gen_neutral.generate_for_filing(
            filing_id=1, company_id=1, segments=[segment], db=db_session
        )

        # Verify different keywords selected
        # (implementation details depend on exact text positioning)
        assert len(candidates_default) >= 1
        assert len(candidates_neutral) >= 1
```

**Estimated Effort**: 45 minutes

---

#### Task C3: Boundary Interaction Test

**Goal**: Verify multiplier applied after boundary filtering

**Test Case**:
```python
def test_multiplier_applied_after_boundary_filtering():
    """
    Boundary filtering happens first, then multiplier sorting.

    Scenario:
    - Pre-value keyword in different bullet point (filtered by boundary)
    - Post-value keyword in same bullet point (kept, then multiplier applied)
    - Result: Post-value wins despite multiplier penalty
    """
    from src.review.boundary_detection import BoundaryDetector

    text = """
    • Active customers increased significantly
    • Revenue was 100 with gross margin improvement
    """

    matcher = KeywordMatcher(
        respect_bullet_boundaries=True,
        post_value_distance_multiplier=0.9
    )
    detector = BoundaryDetector()
    boundaries = detector.find_boundaries(text)

    all_keywords = matcher.find_all_keywords(text)

    # Number "100" in second bullet
    number = NumberMatch(start=..., end=..., raw_text="100", ...)

    keywords = matcher.find_keywords_near_number(
        number, all_keywords, boundaries=boundaries
    )

    # Should find "gross margin" (same bullet, post-value)
    # Should NOT find "active customers" (different bullet, filtered out)
    assert len(keywords) >= 1
    assert "margin" in keywords[0].keyword.lower()
```

**Estimated Effort**: 30 minutes

---

#### Task C4: Multiple Keywords Test

**Goal**: Verify correct sorting with multiple pre and post keywords

**Test Case**:
```python
def test_multiple_pre_and_post_keywords_sorted_correctly():
    """
    Multiple pre-value and post-value keywords sorted by effective distance.

    Setup:
    - Pre-value 1: 50 chars away (effective: 50)
    - Post-value 1: 60 chars away (effective: 66.7 with 0.9)
    - Pre-value 2: 100 chars away (effective: 100)
    - Post-value 2: 120 chars away (effective: 133.3 with 0.9)

    Expected order: Pre-1 < Post-1 < Pre-2 < Post-2
    """
    matcher = KeywordMatcher(
        max_keyword_distance=200,
        prefer_closest_keyword=True,
        post_value_distance_multiplier=0.9,
    )

    # Construct text with precise keyword positioning
    text = (
        "revenue"        # Pre-1: 0-7 (distance to 100: 50 chars)
        + " " * 42
        + "100"          # Number at position 50-53
        + " " * 7
        + "margin"       # Post-1: 60-66 (distance: 60, effective: 66.7)
        + " " * 33
        + "customers"    # Pre-2 or Post-2 depending on position...
    )

    all_keywords = matcher.find_all_keywords(text)
    number = NumberMatch(start=50, end=53, raw_text="100", ...)

    # Find all keywords (should return multiple for different metrics)
    keywords = matcher.find_keywords_near_number(number, all_keywords)

    # Verify sorting order by checking effective distances
    # (exact assertions depend on text construction)
```

**Estimated Effort**: 30 minutes

---

### Workstream D: Documentation Improvements (P2 - MEDIUM)

**Objective**: Improve documentation to explain L4 logic and design decisions

**Status**: ⏭️ Ready to Implement

#### Task D1: Update CLAUDE.md

**Changes**:
- Add L4 to L-series completion table
- Explain post-value distance multiplier
- Document business rationale decision (after A1)
- Add configuration examples

**Location**: `CLAUDE.md` → Review Module Architecture section

**Estimated Effort**: 20 minutes

---

#### Task D2: Update METRIC_IDENTIFICATION_ISSUES.md

**Changes**:
- Update Issue 5 status to reflect L4 resolution
- Document chosen business logic (after A1)
- Explain why pre-value or post-value was preferred
- Add examples of how multiplier works

**Location**: `METRIC_IDENTIFICATION_ISSUES.md` → Issue 5 section

**Estimated Effort**: 15 minutes

---

#### Task D3: Enhance Config Docstring

**Changes**:
- Expand `post_value_distance_multiplier` docstring
- Add mathematical examples
- Explain when to adjust multiplier
- Document context-dependent logic (if A3 implemented)

**Location**: `src/review/config.py:80-86`

**Example**:
```python
post_value_distance_multiplier: float = 0.9
"""Multiplier applied to effective distance for keywords appearing AFTER values.

SEC filings typically list metrics BEFORE their values (e.g., "Net Revenue of $1.2M").
When keywords are equidistant from a number, this multiplier gives preference to
pre-value keywords by PENALIZING post-value keywords.

Mathematical Effect:
- Pre-value keyword at 100 chars: effective distance = 100
- Post-value keyword at 100 chars: effective distance = 100 / 0.9 = 111.11
- Result: Pre-value keyword wins (100 < 111.11)

For post-value to win at equal raw distance, multiplier would need to be > 1.0.
For stronger pre-value preference, use multiplier < 0.9 (e.g., 0.8).

Typical values:
- 0.9: Slight pre-value preference (default, general use)
- 1.0: No preference (neutral)
- 0.8: Strong pre-value preference (bullet points, lists)
- 1.1: Slight post-value preference (clarifications, not implemented)

L4 enhancement.
"""
```

**Estimated Effort**: 15 minutes

---

#### Task D4: Add KeywordMatcher Docstring

**Changes**:
- Add comprehensive docstring to `find_keywords_near_number()`
- Explain multiplier application
- Document Phase 3 sorting logic
- Add examples

**Location**: `src/review/keyword_matching.py:240-422`

**Estimated Effort**: 10 minutes

---

### Workstream E: Debug Logging Enhancement (P3 - LOW)

**Objective**: Add logging to track when multiplier changes outcomes

**Status**: ⏭️ Ready to Implement (Optional)

#### Task E1: Add Outcome Logging

**Goal**: Log when L4 multiplier changes which keyword is selected

**Implementation**:
```python
# After sorting in Phase 3, check if multiplier changed outcome
if self.prefer_closest_keyword and len(candidates_with_effective_distance) > 1:
    winner = candidates_with_effective_distance[0]
    runner_up = candidates_with_effective_distance[1]

    winner_kw, winner_raw, winner_eff = winner
    runner_up_kw, runner_up_raw, runner_up_eff = runner_up

    # Check if winner is pre-value and runner-up is post-value
    if (
        winner_kw.direction == "before"
        and runner_up_kw.direction == "after"
        and runner_up_raw < winner_raw  # Runner-up closer in raw distance
    ):
        logger.debug(
            f"L4 multiplier effect: pre-value '{winner_kw.keyword}' won over "
            f"closer post-value '{runner_up_kw.keyword}' for number '{number.raw_text}' "
            f"(raw distances: {winner_raw} vs {runner_up_raw}, "
            f"effective: {winner_eff:.1f} vs {runner_up_eff:.1f})"
        )
```

**Configuration**:
```python
# Add to CandidateGenerationConfig
log_l4_effects: bool = False  # Default off to reduce noise
```

**Estimated Effort**: 30 minutes

---

## Summary: Task Effort Estimates

| Workstream | Task | Priority | Effort | Dependencies |
|------------|------|----------|--------|--------------|
| **A** | A1: User consultation | P0 | 45 min | None |
| **A** | A2: Implement chosen logic | P0 | 30min-4hr | A1 |
| **A** | A3: Context-dependent spec | P0 | 3-4 hr | A1, if Option C |
| **B** | B1: Fix ambiguity logging | P1 | 1 hr | None |
| **C** | C1: Threshold test | P1 | 30 min | None |
| **C** | C2: Integration test | P1 | 45 min | None |
| **C** | C3: Boundary interaction test | P1 | 30 min | None |
| **C** | C4: Multiple keywords test | P1 | 30 min | None |
| **D** | D1: Update CLAUDE.md | P2 | 20 min | A1 (decision) |
| **D** | D2: Update issues doc | P2 | 15 min | A1 (decision) |
| **D** | D3: Config docstring | P2 | 15 min | None |
| **D** | D4: Matcher docstring | P2 | 10 min | None |
| **E** | E1: Debug logging | P3 | 30 min | None |

**Total Effort Range**: 5.5 - 10 hours (depending on A2/A3 option chosen)

---

## Recommended Implementation Sequence

### Phase 1: Critical Path (P0 + P1)

**Goal**: Fix critical issues and bring to production quality

**Sequence**:
1. **A1**: User consultation (45 min) → BLOCKS A2, A3
2. **Parallel Block 1** (after A1):
   - **A2 or A3**: Implement business logic (30min - 4hr)
   - **B1**: Fix ambiguity logging (1 hr)
3. **Parallel Block 2**:
   - **C1**: Threshold test (30 min)
   - **C2**: Integration test (45 min)
   - **C3**: Boundary interaction test (30 min)
   - **C4**: Multiple keywords test (30 min)

**Total Time**: 5.5 - 9 hours
**Parallelization**: Tasks in same block can run concurrently

---

### Phase 2: Polish (P2)

**Goal**: Improve documentation and discoverability

**Sequence**:
1. **D1**: Update CLAUDE.md (20 min)
2. **D2**: Update issues doc (15 min)
3. **D3**: Config docstring (15 min)
4. **D4**: Matcher docstring (10 min)

**Total Time**: 1 hour
**Can be done in parallel with Phase 1 tasks C1-C4**

---

### Phase 3: Optional Enhancements (P3)

**Goal**: Add debug tooling

**Sequence**:
1. **E1**: Debug logging (30 min)

**Total Time**: 30 minutes
**Can be deferred to future sprint**

---

## Success Criteria

### Phase 1 (P0 + P1)
- [ ] Business rationale decided and documented
- [ ] Context-dependent logic implemented (if chosen)
- [ ] Ambiguity logging uses effective distance
- [ ] All new tests pass (4+ tests added)
- [ ] Existing tests still pass
- [ ] `mypy --strict` passes

### Phase 2 (P2)
- [ ] CLAUDE.md updated with L4 details
- [ ] METRIC_IDENTIFICATION_ISSUES.md Issue 5 updated
- [ ] Config docstrings enhanced
- [ ] KeywordMatcher docstrings enhanced

### Phase 3 (P3)
- [ ] Debug logging implemented
- [ ] Config flag added for enabling/disabling

### Overall Success
- [ ] L4 grade improved from B- to A-
- [ ] No regressions in existing functionality
- [ ] Test coverage > 90% for L4 code
- [ ] Documentation complete and clear

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Context-dependent logic too complex | Medium | High | Start simple, iterate based on metrics |
| User can't decide business rationale | Low | High | Provide data: sample 50 filings, measure patterns |
| Tests reveal bugs in current implementation | Medium | Medium | Fix bugs as discovered, may extend timeline |
| Multiplier doesn't improve extraction quality | Low | High | A/B test with human review data |

---

## Next Steps

1. **Immediate**: Review evaluation and plan with user
2. **User Decision**: Schedule Task A1 consultation (45 min)
3. **After A1**: Begin parallel implementation of B1 + C1-C4
4. **After A1**: Implement A2 or A3 based on decision
5. **Polish**: Complete D1-D4 documentation
6. **Optional**: Implement E1 debug logging if time permits

---

**Plan Author**: Claude Code (AI Assistant)
**Plan Date**: 2025-12-15
**Next Review**: After Phase 1 completion

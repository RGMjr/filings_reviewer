# WORKER PROMPT: Task GR-7 - Add Engagement & Conversion Patterns

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-7
TASK NAME:     Add patterns for engagement and conversion metrics
WORKSTREAM:    Pattern Coverage
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🟡 PENDING
TIME ESTIMATE: 2.5 hours (research 45 min, implementation 60 min, testing 45 min)
RISK LEVEL:    LOW (additive patterns, no breaking changes)
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    None
UNLOCKS:       GR-10 (validation)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-2, GR-4, GR-6, GR-8, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add engagement and conversion metric patterns to improve goldmine detection for consumer social, media, and freemium businesses.

**Business Rationale**: Consumer-facing companies (Instagram, Pinterest, Spotify-style) disclose engagement metrics (session duration, sessions per user) and conversion metrics (free-to-paid, trial conversion) that our current patterns don't capture. These are high-value disclosures that help investors understand user behavior and monetization.

**Current Behavior**: Engagement and conversion terms are not detected, resulting in lower richness scores for consumer/social media/freemium filing segments.

**Desired Behavior**: Engagement and conversion terminology triggers usage or retention bonuses, improving goldmine detection for these industry segments.

## Prerequisites

- None (standalone task)
- Understanding of existing pattern structure in segment_enricher.py helpful

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add engagement/conversion patterns
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add engagement/conversion pattern tests

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 60-200 - Existing pattern structure
- `src/extraction/segment_enricher.py` RETENTION_KEYWORDS - Similar pattern for reference

## Implementation Requirements

### Core Functionality

1. **Add Engagement Keyword Patterns**
   - `r"\b(?:average\s+)?session\s+(?:duration|length)\b"` - Session duration/length
   - `r"\bsessions?\s+per\s+(?:user|customer|member)\b"` - Sessions per user
   - `r"\btime\s+(?:spent|on\s+platform|in\s+app)\b"` - Time spent engagement
   - `r"\bengagement\s+(?:rate|score|metric)\b"` - Engagement rate/score

2. **Add Conversion Keyword Patterns**
   - `r"\bconversion\s+rate\b"` - Conversion rate
   - `r"\bfree[- ]to[- ]paid\s+conversion\b"` - Free-to-paid conversion
   - `r"\btrial\s+conversion(?:\s+rate)?\b"` - Trial conversion
   - `r"\b(?:paid\s+)?subscriber\s+conversion\b"` - Subscriber conversion

3. **Pattern Organization Options**

   Option A: Add to USAGE_KEYWORDS (simpler, engagement is a form of usage)

   Option B: Create new ENGAGEMENT_PATTERNS and CONVERSION_PATTERNS lists (more organized)
   - Allows separate detection logic if needed
   - Could enable future separate bonuses

4. **Integration with Scoring**
   - Patterns should contribute to richness score
   - Follow same pattern as existing USAGE_KEYWORDS or RETENTION_KEYWORDS
   - Engagement patterns could trigger `contains_usage_keywords`
   - Conversion patterns might trigger retention or usage bonus

### Error Handling

- Regex patterns must compile without errors
- Case-insensitive matching (use `re.IGNORECASE`)

### Performance Requirements

- Compile patterns as class-level constants
- Follow existing pattern compilation style

## Test Requirements

### Coverage Target: Maintain existing coverage for `segment_enricher.py`

### Test Categories (10+ tests)

1. **Session/Time Engagement** (3 tests)
   - "average session duration was 25 minutes" → detected
   - "sessions per user increased 15%" → detected
   - "time spent on platform" → detected

2. **Engagement Rate Detection** (2 tests)
   - "engagement rate improved to 45%" → detected
   - "engagement score" → detected

3. **Conversion Detection** (4 tests)
   - "conversion rate of 3.5%" → detected
   - "free-to-paid conversion reached 12%" → detected
   - "trial conversion rate" → detected
   - "paid subscriber conversion" → detected

4. **Negative Cases** (2+ tests)
   - "convert" (verb form, not metric) → NOT detected
   - "session" alone without duration/length → NOT detected (too generic)
   - "engaged customers" → verify if should match or not

### Known Edge Cases to Test

- Hyphenation: "free-to-paid" vs "free to paid"
- Variations: "session length" vs "session duration"
- Combined: "average session duration per user"

## Acceptance Criteria

- [ ] 8+ engagement/conversion patterns added
- [ ] Patterns are case-insensitive
- [ ] Patterns compiled as class-level constants
- [ ] Patterns integrate with richness scoring
- [ ] 10+ unit tests covering engagement/conversion patterns
- [ ] All existing tests pass
- [ ] No false positives for generic terms ("session", "convert")
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Modify threshold values (GR-1 handles that)
- Add subscriber patterns (GR-2 handles that)
- Add platform/marketplace patterns (GR-6 handles that)
- Create a completely new detection system (follow existing pattern structure)

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "engagement or conversion or session" --tb=short

# Run all enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Verify patterns compile
python3 -c "import re; re.compile(r'\bconversion\s+rate\b', re.IGNORECASE); print('Patterns compile OK')"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# Example: Adding engagement and conversion patterns
# In segment_enricher.py

ENGAGEMENT_PATTERNS: list[Pattern[str]] = [
    re.compile(r"\b(?:average\s+)?session\s+(?:duration|length)\b", re.IGNORECASE),
    re.compile(r"\bsessions?\s+per\s+(?:user|customer|member)\b", re.IGNORECASE),
    re.compile(r"\btime\s+(?:spent|on\s+platform|in\s+app)\b", re.IGNORECASE),
    re.compile(r"\bengagement\s+(?:rate|score|metric)\b", re.IGNORECASE),
]

CONVERSION_PATTERNS: list[Pattern[str]] = [
    re.compile(r"\bconversion\s+rate\b", re.IGNORECASE),
    re.compile(r"\bfree[- ]to[- ]paid\s+conversion\b", re.IGNORECASE),
    re.compile(r"\btrial\s+conversion(?:\s+rate)?\b", re.IGNORECASE),
    re.compile(r"\b(?:paid\s+)?subscriber\s+conversion\b", re.IGNORECASE),
]

def _detect_engagement_metrics(self, text: str) -> bool:
    """Detect engagement metric patterns."""
    return any(pattern.search(text) for pattern in self.ENGAGEMENT_PATTERNS)

def _detect_conversion_metrics(self, text: str) -> bool:
    """Detect conversion metric patterns."""
    return any(pattern.search(text) for pattern in self.CONVERSION_PATTERNS)
```
</details>

## Expected Impact

**Before GR-7**:
- Consumer social filings: Lower richness scores
- "Session duration" not detected as engagement metric
- "Free-to-paid conversion" not captured

**After GR-7**:
- Consumer social filings: +0.5 to +1.5 richness score boost
- Engagement and conversion terminology properly detected
- Better goldmine recall for consumer/social/freemium S-1s

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4

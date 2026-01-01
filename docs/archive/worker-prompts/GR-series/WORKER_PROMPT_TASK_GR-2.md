# WORKER PROMPT: Task GR-2 - Add Subscriber Metric Patterns

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-2
TASK NAME:     Extend usage patterns to capture subscriber metrics
WORKSTREAM:    Pattern Coverage
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 0 Quick Wins
STATUS:        🟡 PENDING
TIME ESTIMATE: 2 hours (research 30 min, implementation 60 min, testing 30 min)
RISK LEVEL:    LOW (additive pattern change, no breaking changes)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       GR-10 (validation)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-4, GR-6, GR-7, GR-8, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add subscriber-related keyword patterns to the usage detection system to improve goldmine detection for solar, telecom, and subscription-based businesses.

**Business Rationale**: Vivint Solar's filings use "subscriber" terminology heavily but score only 3.8 (missing 1.0+ usage bonus). Adding subscriber patterns would boost scores to 4.8-5.3, enabling goldmine detection for subscription businesses.

**Current Behavior**: Subscriber-related terms ("total subscribers", "subscriber base") are not detected as usage metrics, missing valuable segment identification.

**Desired Behavior**: Subscriber terms are detected as usage metrics, triggering the tiered usage bonus (+1.0 for subscriber counts, +0.75 for subscriber keywords with context).

## Prerequisites

- None (standalone task)
- Familiarity with existing usage pattern structure in segment_enricher.py helpful

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add subscriber patterns to `USAGE_KEYWORDS` and/or `USAGE_WITH_COUNT_PATTERNS`
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add subscriber pattern tests (or create new test file)

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 100-200 - Existing usage pattern structure
- `docs/GOLDMINE_REMEDIATION_PLAN.md` - Pattern specifications

## Implementation Requirements

### Core Functionality

1. **Add Subscriber Keywords to USAGE_KEYWORDS List**
   - "subscriber" (singular)
   - "subscribers" (plural)
   - "subscriber base"
   - "subscriber count"
   - "total subscribers"

2. **Add Subscriber Count Pattern to USAGE_WITH_COUNT_PATTERNS**
   - Numeric subscribers: Pattern to match "10 million subscribers", "1.5M subscribers", "500,000 subscribers"
   - Example regex: `r"\b\d+(?:[,\.]\d+)?(?:\s*(?:million|billion|M|B|K))?\s+subscribers?\b"`

3. **Integration with Tiered Usage Bonus**
   - Subscriber keywords should trigger existing usage detection logic
   - Subscriber + count should trigger the +1.0 usage bonus
   - Subscriber keyword alone should trigger +0.5 or +0.75 bonus per existing tiers

### Error Handling

- Regex patterns must be valid (compile-time check)
- Case-insensitive matching (use `re.IGNORECASE`)
- No exceptions on malformed text

### Performance Requirements

- New patterns should not significantly impact processing time
- Use compiled regex patterns (follow existing pattern for `USAGE_KEYWORDS`)

## Test Requirements

### Coverage Target: Maintain existing coverage for `segment_enricher.py`

### Test Categories (8+ tests)

1. **Subscriber Keyword Detection** (4 tests)
   - "We have 10 million subscribers" → usage detected
   - "Our subscriber base grew 50%" → usage detected
   - "Total subscribers reached 5.2 million" → usage detected
   - "subscriber count" detection

2. **Subscriber with Count Pattern** (2 tests)
   - "10 million subscribers" → usage_with_count = True
   - "500K subscribers" → usage_with_count = True

3. **Negative Cases** (2 tests)
   - "subscription" (related but different term) - should NOT match if not in scope
   - "describe" (false positive check for "scribe" substring) - must NOT match

### Known Edge Cases to Test

- "1.5 million paid subscribers" (numeric with qualifier)
- "subscribers" at end of sentence
- Case variations: "Subscribers", "SUBSCRIBERS"

## Acceptance Criteria

- [ ] Subscriber keywords added to usage detection
- [ ] Subscriber count pattern added to USAGE_WITH_COUNT_PATTERNS
- [ ] Patterns are case-insensitive
- [ ] 8+ new unit tests covering subscriber patterns
- [ ] All existing tests pass
- [ ] No false positives for "subscription", "describe", "subscribe" (action verb)
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Modify threshold values (GR-1 handles that)
- Add platform or engagement patterns (GR-6, GR-7 handle those)
- Change the tiered bonus calculation logic (that's already complete in GR-3)
- Create new test files unless test_segment_enricher.py would become too large

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "subscriber" --tb=short

# Run all enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Verify patterns compile
python3 -c "import re; re.compile(r'\b\d+(?:[,\.]\d+)?(?:\s*(?:million|billion|M|B|K))?\s+subscribers?\b', re.IGNORECASE)"
```

## Expected Impact

**Before GR-2**:
- Vivint Solar segment score: 3.8
- Subscriber terms: Not detected as usage
- Subscription industries: Underrepresented in goldmines

**After GR-2**:
- Vivint Solar segment score: 4.8-5.3 (+1.0 to +1.5)
- Subscriber terms: Detected with tiered bonuses
- Solar, telecom, SaaS industries: Improved goldmine detection

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4

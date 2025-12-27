# WORKER PROMPT: Task GR-6 - Add Platform & Marketplace Patterns

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-6
TASK NAME:     Add patterns for platform metrics (listings, transactions, merchants)
WORKSTREAM:    Pattern Coverage
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🟡 PENDING
TIME ESTIMATE: 2.5 hours (research 45 min, implementation 60 min, testing 45 min)
RISK LEVEL:    LOW (additive patterns, no breaking changes)
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    None
UNLOCKS:       GR-10 (validation)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-2, GR-4, GR-7, GR-8, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add platform and marketplace metric patterns to improve goldmine detection for e-commerce and platform businesses like Etsy, Shopify, Uber, Airbnb, and PropertyGuru.

**Business Rationale**: Platform businesses use specific terminology ("active listings", "GMV per merchant", "marketplace transactions") that our current patterns don't capture. These companies represent a significant portion of high-profile S-1 filings with valuable customer metric disclosures.

**Current Behavior**: Platform-specific terms are not detected, resulting in lower richness scores for marketplace/platform filing segments.

**Desired Behavior**: Platform metric terminology triggers usage or business activity bonuses, improving goldmine detection for this industry segment.

## Prerequisites

- None (standalone task)
- Understanding of existing pattern structure in segment_enricher.py helpful

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add platform patterns (new pattern list or extend existing USAGE_KEYWORDS)
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add platform pattern tests

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 60-200 - Existing pattern structure
- Sample S-1 filings from Etsy, Shopify (if available in test fixtures)

## Implementation Requirements

### Core Functionality

1. **Add Platform/Marketplace Keyword Patterns**

   Option A: Add to USAGE_KEYWORDS (simpler):
   - "active listings"
   - "total merchants"
   - "active merchants"
   - "active sellers"
   - "platform transactions"
   - "marketplace transactions"

   Option B: Create new PLATFORM_KEYWORDS list (more organized):
   - Allows separate detection and bonus logic if needed
   - Recommended if patterns need different bonus treatment

2. **Patterns to Add (required)**
   - `r"\bactive\s+listings?\b"` - Active listings/listing
   - `r"\b(?:marketplace|platform)\s+transactions?\b"` - Platform/marketplace transactions
   - `r"\btotal\s+(?:merchants?|sellers?|vendors?)\b"` - Total merchants/sellers/vendors
   - `r"\bactive\s+(?:merchants?|sellers?)\b"` - Active merchants/sellers
   - `r"\bGMV\s+per\s+(?:merchant|seller)\b"` - GMV per merchant/seller
   - `r"\bplatform\s+engagement\b"` - Platform engagement

3. **Integration with Scoring**
   - Platform keywords should contribute to richness score
   - Follow same pattern as existing USAGE_KEYWORDS (likely +0.5 base, +1.0 with count)
   - Consider if these should trigger `contains_usage_keywords` or a new flag

### Error Handling

- Regex patterns must compile without errors
- Case-insensitive matching (use `re.IGNORECASE`)

### Performance Requirements

- Compile patterns as class-level constants (not per-segment)
- Follow existing pattern compilation style

## Test Requirements

### Coverage Target: Maintain existing coverage for `segment_enricher.py`

### Test Categories (10+ tests)

1. **Listing Detection** (2 tests)
   - "We had 50 million active listings" → detected
   - "active listing" (singular) → detected

2. **Merchant/Seller Detection** (3 tests)
   - "total merchants exceeded 2 million" → detected
   - "active sellers grew 40%" → detected
   - "vendors" variation → detected

3. **Transaction Detection** (2 tests)
   - "platform transactions reached $10B" → detected
   - "marketplace transactions grew 25%" → detected

4. **GMV Patterns** (2 tests)
   - "GMV per merchant increased" → detected
   - "GMV per seller" → detected

5. **Negative Cases** (2+ tests)
   - "listing" without "active" → NOT detected (too generic)
   - "merchant account" → NOT detected (different meaning)

### Known Edge Cases to Test

- Plural variations: "listings" vs "listing", "merchants" vs "merchant"
- Case variations: "Active Listings", "ACTIVE LISTINGS"
- Combined patterns: "active marketplace listings"

## Acceptance Criteria

- [ ] 6+ platform/marketplace patterns added
- [ ] Patterns are case-insensitive
- [ ] Patterns compiled as class-level constants
- [ ] Platform keywords integrate with richness scoring
- [ ] 10+ unit tests covering platform patterns
- [ ] All existing tests pass
- [ ] No false positives for generic terms ("listing" alone, "merchant" alone)
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Modify threshold values (GR-1 handles that)
- Add subscriber patterns (GR-2 handles that)
- Add engagement/conversion patterns (GR-7 handles that)
- Create a completely new detection system (follow existing pattern structure)

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "platform or marketplace or merchant or listing" --tb=short

# Run all enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Verify patterns compile
python3 -c "import re; re.compile(r'\bactive\s+listings?\b', re.IGNORECASE); print('Patterns compile OK')"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# Example: Adding to existing USAGE_KEYWORDS pattern
# In segment_enricher.py, find USAGE_KEYWORDS and add:

PLATFORM_PATTERNS: list[Pattern[str]] = [
    re.compile(r"\bactive\s+listings?\b", re.IGNORECASE),
    re.compile(r"\b(?:marketplace|platform)\s+transactions?\b", re.IGNORECASE),
    re.compile(r"\btotal\s+(?:merchants?|sellers?|vendors?)\b", re.IGNORECASE),
    re.compile(r"\bactive\s+(?:merchants?|sellers?)\b", re.IGNORECASE),
    re.compile(r"\bGMV\s+per\s+(?:merchant|seller)\b", re.IGNORECASE),
    re.compile(r"\bplatform\s+engagement\b", re.IGNORECASE),
]

# In _detect_platform_metrics() or extend _detect_usage_metrics():
def _detect_platform_metrics(self, text: str) -> bool:
    """Detect platform/marketplace metric patterns."""
    return any(pattern.search(text) for pattern in self.PLATFORM_PATTERNS)
```
</details>

## Expected Impact

**Before GR-6**:
- Platform filings (Etsy, Shopify, Uber): Lower richness scores
- "Active listings" not detected as usage metric
- Marketplace terminology missed

**After GR-6**:
- Platform filings: +0.5 to +1.5 richness score boost
- Platform metric terminology properly detected
- Better goldmine recall for e-commerce/marketplace S-1s

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4

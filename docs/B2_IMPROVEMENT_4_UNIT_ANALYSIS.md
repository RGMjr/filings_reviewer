# B2 Improvement #4: Unit Value Mapping Analysis

## Summary

Verified that `number_unit` values passed to `FeatureExtractor.determine_number_format()` match expectations. Found **critical mismatches** between ValueExtractor and FeatureExtractor unit formats.

## Expected Unit Values

`FeatureExtractor.determine_number_format()` expects (from src/review/feature_extractor.py:105):
- `"%"` for percentages
- `"usd"` for currency
- `"count"` for plain numbers (falls through to integer/decimal based on raw_text)

## Actual Unit Values by Source

### 1. NumberParser (Review System)
**Source**: `src/review/number_parsing.py:160-168`

**Produces**:
- `"%"` for percentages ✓
- `"usd"` for currency ✓
- `"count"` for plain numbers ✓

**Status**: ✅ **CORRECT** - Matches FeatureExtractor expectations

**Flow**:
```
NumberParser.parse_number() → NumberMatch.unit → CandidateGenerator._compute_features()
→ FeatureExtractor.compute_features(number_unit=...) → determine_number_format()
```

### 2. ValueExtractor (Extraction Pipeline)
**Source**: `src/extraction/value_extractor.py:940-963`

**Produces**:
- `"percent"` for percentages ❌ (expects "%")
- `"usd"` for currency ✓
- `"count"` for plain numbers ✓

**Status**: ⚠️ **MISMATCH** - Returns "percent" instead of "%"

**Impact**: If MetricValue.unit is used in feature extraction, percentages would be classified as "integer" or "decimal" instead of "percentage"

**Code**:
```python
def _infer_unit(self, value_text: str, metric_id: str) -> Optional[str]:
    # ...
    if "%" in value_text or "percent" in value_lower:
        return "percent"  # ❌ Should be "%"
```

### 3. LLM Extraction (Via Prompts)
**Source**: `src/llm/prompts.py:162-166, 198`

**Produces** (from LLM responses):
- `"percent"` for percentages ❌ (expects "%")
- `"dollars"` or `"currency"` for monetary values ❌ (expects "usd")
- `"count"`, `"thousands"`, `"millions"` for counts ⚠️ (expects "count")

**Status**: ⚠️ **MULTIPLE MISMATCHES**

**Impact**: LLM-extracted values would have incorrect number_format classification

**Example LLM Output**:
```json
{
  "metric_name": "net_revenue_retention",
  "value": "130",
  "units": "percent",  // ❌ Should be "%"
  "period": "Year 2"
}
```

## Current vs. Expected Mapping

| Source | Percentages | Currency | Counts |
|--------|-------------|----------|--------|
| **Expected** | `"%"` | `"usd"` | `"count"` |
| NumberParser | `"%"` ✓ | `"usd"` ✓ | `"count"` ✓ |
| ValueExtractor | `"percent"` ❌ | `"usd"` ✓ | `"count"` ✓ |
| LLM | `"percent"` ❌ | `"dollars"`, `"currency"` ❌ | `"count"`, `"thousands"`, `"millions"` ⚠️ |

## Consequences of Mismatches

### Percentage Mismatch
```python
# Current behavior with "percent":
determine_number_format(number_unit="percent", number_raw_text="45.5")
# Returns: "decimal" ❌ (falls through to check for ".")
# Expected: "percentage"
```

### Currency Mismatch (LLM)
```python
# Current behavior with "dollars":
determine_number_format(number_unit="dollars", number_raw_text="1234567")
# Returns: "integer" ❌ (falls through to default)
# Expected: "currency"
```

### Count Variations (LLM)
```python
# Current behavior with "millions":
determine_number_format(number_unit="millions", number_raw_text="10.5")
# Returns: "decimal" ⚠️ (works but semantic meaning lost)
# Expected: Could classify as "count" with magnitude in value
```

## Recommendations

### Option 1: Normalize Units in FeatureExtractor (Recommended)
**Pros**:
- Backward compatible
- Handles all input variations
- Defensive against future changes
- Single point of normalization

**Cons**:
- Adds complexity to FeatureExtractor

**Implementation**:
```python
def _normalize_unit(self, number_unit: Optional[str]) -> Optional[str]:
    """Normalize unit variations to canonical format."""
    if not number_unit:
        return None

    unit_lower = number_unit.lower().strip()

    # Percentage variations
    if unit_lower in ("percent", "percentage", "pct"):
        return "%"

    # Currency variations
    if unit_lower in ("dollars", "currency", "dollar", "$"):
        return "usd"

    # Count variations (normalize to "count")
    if unit_lower in ("thousands", "millions", "billions", "k", "m", "b"):
        return "count"

    # Already normalized
    return number_unit
```

### Option 2: Fix ValueExtractor
**Pros**:
- Removes inconsistency at source
- Cleaner architecture

**Cons**:
- Doesn't fix LLM responses
- Requires updating MetricValue.unit documentation
- May affect existing extractions in database

### Option 3: Update LLM Prompts
**Pros**:
- Fixes LLM output format

**Cons**:
- Doesn't guarantee compliance (LLM may ignore instructions)
- Still need to handle existing data
- Doesn't fix ValueExtractor

## Recommended Solution

**Implement all three fixes in order**:

1. **Immediate**: Add unit normalization to FeatureExtractor (Option 1)
   - Provides defensive handling of all unit variations
   - Zero breaking changes
   - Handles historical data

2. **Follow-up**: Update ValueExtractor (Option 2)
   - Change `return "percent"` to `return "%"` (line 950)
   - Ensures new extractions use canonical format
   - Update docstring and tests

3. **Optional**: Update LLM prompts (Option 3)
   - Add examples showing `"units": "%"` instead of `"units": "percent"`
   - Add validation note: "Use '%' not 'percent'"
   - Note: LLM compliance not guaranteed, so normalization still needed

## Files to Modify

1. **src/review/feature_extractor.py**
   - Add `_normalize_unit()` method
   - Call from `determine_number_format()`
   - Update docstring to document accepted variations

2. **src/extraction/value_extractor.py**
   - Line 950: Change `return "percent"` to `return "%"`
   - Update docstring on `_infer_unit()` method

3. **tests/unit/review/test_feature_extractor.py**
   - Add tests for unit normalization
   - Test variations: "percent", "percentage", "dollars", "currency", etc.

4. **tests/unit/extraction/test_value_extractor.py**
   - Update expected unit values in tests
   - Verify `_infer_unit()` returns "%" not "percent"

## Current Usage in Codebase

### CandidateGenerator ✅
- Uses NumberParser which produces correct units
- No changes needed

### Extraction Pipeline ⚠️
- ValueExtractor produces "percent"
- MetricValue stores in database
- **Issue**: If MetricValue.unit is ever used for feature extraction, would fail

### Human Review System ✅
- Currently only uses NumberParser
- FeatureExtractor works correctly with NumberParser units

## Test Coverage Needed

```python
def test_normalize_percent_variations():
    assert determine_number_format("percent", "45") == "percentage"
    assert determine_number_format("percentage", "45") == "percentage"
    assert determine_number_format("pct", "45") == "percentage"
    assert determine_number_format("%", "45") == "percentage"

def test_normalize_currency_variations():
    assert determine_number_format("dollars", "1234") == "currency"
    assert determine_number_format("currency", "1234") == "currency"
    assert determine_number_format("dollar", "1234") == "currency"
    assert determine_number_format("usd", "1234") == "currency"

def test_normalize_count_variations():
    assert determine_number_format("thousands", "10") == "integer"
    assert determine_number_format("millions", "10.5") == "decimal"
    assert determine_number_format("count", "100") == "integer"
```

## Priority

**HIGH** - This affects feature classification accuracy in the review system and may cause incorrect confidence scoring for candidates with percentage metrics.

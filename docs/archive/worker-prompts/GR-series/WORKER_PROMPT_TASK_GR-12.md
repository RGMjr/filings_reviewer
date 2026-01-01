# WORKER PROMPT: Task GR-12 - Add EnrichmentMetadata TypedDict

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-12
TASK NAME:     Type-safe schema for extra_metadata enrichment fields
WORKSTREAM:    Type Safety
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 2 Code Quality
STATUS:        🟡 PENDING
TIME ESTIMATE: 1.5 hours (implementation 45 min, testing 30 min, mypy check 15 min)
RISK LEVEL:    NONE (type safety improvement, no runtime changes)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       Better IDE autocomplete, compile-time typo detection
BLOCKS:        None
PARALLEL WITH: GR-11, GR-13, GR-14, GR-16, GR-17
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a TypedDict for enrichment metadata fields that are stored in `extra_metadata`, providing type safety, autocomplete, and compile-time typo detection.

**Business Rationale**: The `extra_metadata` dictionary on segments stores enrichment flags like `contains_saas_indicator`, `contains_usage_keywords`, etc. Currently these are untyped dict keys, making typos invisible until runtime. A TypedDict provides:
- IDE autocomplete for metadata keys
- Compile-time detection of key typos
- Clear documentation of the metadata schema

**Current Behavior**: `extra_metadata` is `dict[str, Any]`, allowing any keys with no type checking.

**Desired Behavior**: `EnrichmentMetadata` TypedDict defines allowed keys and their types, used in `_enrich_segment()`.

## Prerequisites

- None (standalone type safety improvement)

## Files to Modify

1. **`src/extraction/models.py`** - Add EnrichmentMetadata TypedDict
2. **`src/extraction/segment_enricher.py`** - Use typed dict in `_enrich_segment()`
3. **`tests/unit/extraction/test_segment_enricher.py`** - Test metadata structure

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 900-950 - Where `extra_metadata` is populated
- `src/extraction/models.py` - Existing model definitions

## Implementation Requirements

### Core Functionality

1. **Create EnrichmentMetadata TypedDict**

   Add to `src/extraction/models.py`:
   ```python
   from typing import TypedDict

   class EnrichmentMetadata(TypedDict, total=False):
       """Type-safe schema for segment enrichment metadata."""

       # Boolean flags
       contains_saas_indicator: bool
       contains_retention_keywords: bool
       contains_usage_keywords: bool
       contains_usage_with_count: bool
       contains_cohort_keywords: bool
       contains_temporal_trends: bool
       contains_definition_flag: bool

       # Numeric enrichment data
       image_count: int
       richness_score: float

       # Optional string data
       detected_patterns: list[str]
   ```

2. **Update segment_enricher.py to Use TypedDict**
   - Import `EnrichmentMetadata` from models
   - In `_enrich_segment()`, declare `metadata: EnrichmentMetadata = {}`
   - Use typed dict throughout the method
   - Type hints help catch typos like `contains_saas_indictor` at compile time

3. **Type Annotation on Return Value**
   - If `_enrich_segment()` returns metadata, annotate return type
   - If segment object stores metadata, consider updating segment class

### Error Handling

- TypedDict is a type hint only - no runtime overhead
- Missing optional keys are allowed (`total=False`)
- Extra keys trigger mypy errors (desired behavior)

### Test Requirements

#### Coverage Target: **Maintain existing coverage** for `segment_enricher.py`

#### Test Categories (5+ tests)

1. **Metadata Structure Tests** (3-4 tests)
   - Verify expected keys are present after enrichment
   - Verify value types are correct (bool for flags, int for counts)
   - Verify no unexpected keys in metadata

2. **Type Safety Verification** (2+ tests)
   - Run mypy to catch type errors
   - Document that typos would be caught at compile time

### Known Edge Cases to Test

- Empty segment produces minimal metadata
- All flags present for richly-featured segment
- Metadata persists through segment lifecycle

## Acceptance Criteria

- [ ] `EnrichmentMetadata` TypedDict added to `src/extraction/models.py`
- [ ] TypedDict includes all enrichment fields used in `segment_enricher.py`
- [ ] `_enrich_segment()` uses typed dict with proper annotations
- [ ] All existing tests pass
- [ ] `mypy src/extraction/models.py src/extraction/segment_enricher.py --strict` passes
- [ ] 5+ unit tests verifying metadata structure
- [ ] No runtime behavior changes

## Do NOT

- Add runtime validation (TypedDict is compile-time only)
- Change the actual metadata keys used (keep backward compatible)
- Modify segment storage or database schema
- Add required fields that break existing code (use `total=False`)

## Verification Commands

```bash
# Type safety check
mypy src/extraction/models.py src/extraction/segment_enricher.py --strict

# Run enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Verify TypedDict is recognized
python3 -c "from src.extraction.models import EnrichmentMetadata; print(EnrichmentMetadata.__annotations__)"

# Test that typos would be caught (should show mypy error)
echo 'from src.extraction.models import EnrichmentMetadata
m: EnrichmentMetadata = {"contains_saas_indictor": True}  # typo' > /tmp/test_typo.py
mypy /tmp/test_typo.py --strict 2>&1 | head -5
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# src/extraction/models.py
from typing import TypedDict

class EnrichmentMetadata(TypedDict, total=False):
    """
    Type-safe schema for segment enrichment metadata.

    All fields are optional (total=False) to allow incremental enrichment.
    """
    # Detection flags
    contains_saas_indicator: bool
    contains_retention_keywords: bool
    contains_usage_keywords: bool
    contains_usage_with_count: bool
    contains_cohort_keywords: bool
    contains_temporal_trends: bool
    contains_definition_flag: bool

    # Counts
    image_count: int

    # Score
    richness_score: float


# Usage in segment_enricher.py
from src.extraction.models import EnrichmentMetadata

def _enrich_segment(self, segment: SourceSegment) -> EnrichmentMetadata:
    metadata: EnrichmentMetadata = {}

    if self._detect_saas_indicators(text):
        metadata["contains_saas_indicator"] = True

    # IDE autocomplete now works!
    # Typos caught at compile time!

    return metadata
```
</details>

## Expected Impact

**Before GR-12**:
- `extra_metadata["contains_saas_indictor"]` typo invisible until runtime
- No IDE autocomplete for metadata keys
- No documentation of metadata schema

**After GR-12**:
- Typos caught by mypy at compile time
- Full IDE autocomplete for metadata keys
- Clear schema documentation in TypedDict
- No runtime changes or performance impact

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4

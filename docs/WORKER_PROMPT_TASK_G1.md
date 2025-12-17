# WORKER PROMPT: Task G1 - Add Richness Fields to Data Model

```
===============================================================================
TASK ID:       G1
TASK NAME:     Add richness metadata fields to SourceSegment data model
WORKSTREAM:    Data Model Enhancement (Stream A - Foundation)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream A: Data Model & Database
STATUS:        ✅ COMPLETE
TIME ESTIMATE: 2-3 hours (design 30 min, implementation 60 min, testing 60 min)
RISK LEVEL:    Low
PARALLEL WITH: None (foundation task - must complete first before G2-G12)
===============================================================================
```

## Objective

Add 6 new optional fields to the `SourceSegment` dataclass to support goldmine section identification. These fields will store computed richness metadata that enables downstream tasks (G4-G12) to score, rank, and cluster high-value segments.

**Business Rationale**: SEC filings contain "goldmine" sections with dense concentrations of customer metrics, definitions, and cohort analysis. Currently, the pipeline lacks any mechanism to identify or prioritize these sections. Adding richness metadata fields is the foundational step that enables all subsequent goldmine detection features.

**Current Behavior**: `SourceSegment` has 17 fields focused on content and classification, but no fields for richness scoring or goldmine indicators.

**Desired Behavior**: `SourceSegment` includes 6 new optional fields that downstream enrichment logic (Task G4+) will populate to enable goldmine identification.

## Prerequisites

- None (this is the foundation task for the Goldmine improvement stream)
- Familiarity with Python dataclasses and type hints

## Files to Modify

1. **`src/extraction/models.py`** - Add 6 new fields to `SourceSegment` dataclass, update `to_dict()` method
2. **`tests/unit/extraction/test_models.py`** - Add unit tests for new fields (create if doesn't exist)

## Files to Read (Context Only)

- `sql/03_create_analysis_schema.sql` - Understand current DB schema for source_segments table (Task G2 will add columns)
- `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - See Stream A specification for field definitions

## Implementation Requirements

### Core Functionality

1. **Add 6 New Fields to SourceSegment Dataclass** (after `definition_merged_count` field, around line 53)

   - `metric_density: Optional[float] = None` - Metrics per 100 characters (computed by enricher)
   - `distinct_metric_count: int = 0` - Count of unique metric IDs in segment
   - `contains_temporal_trend: bool = False` - True if segment discusses multiple time periods
   - `contains_cohort_breakdown: bool = False` - True if segment contains cohort analysis patterns
   - `image_count: int = 0` - Count of meaningful images/charts in segment
   - `richness_score: Optional[float] = None` - Composite score 0-10 (computed by enricher)

2. **Update to_dict() Method** (lines 59-84)

   - Add all 6 new fields to the returned dictionary
   - Fields should be added after the existing context preservation fields
   - Match the key names exactly to the field names

3. **Type Safety**

   - All new fields must have appropriate type hints
   - Optional fields use `Optional[float]` or `Optional[int]`
   - Boolean fields default to `False`, int fields default to `0`
   - `metric_density` and `richness_score` are Optional because they're computed post-classification

4. **Backward Compatibility**

   - All new fields have defaults, so existing code creating SourceSegment instances continues to work
   - No changes to the constructor signature (dataclass handles defaults)

### Data Model Reference

```python
# Fields to add (reference structure - implement your own version)
@dataclass
class SourceSegment:
    # ... existing 17 fields ...

    # Richness metadata (computed post-classification by SegmentEnricher in Task G4+)
    metric_density: Optional[float] = None          # metrics per 100 chars
    distinct_metric_count: int = 0                   # unique metrics in segment
    contains_temporal_trend: bool = False            # multiple time periods detected
    contains_cohort_breakdown: bool = False          # cohort analysis patterns
    image_count: int = 0                             # meaningful images/charts
    richness_score: Optional[float] = None           # composite score (0-10)
```

### Error Handling

- No explicit error handling needed - dataclass defaults handle all cases
- Type validation is handled by Python's type system

## Test Requirements

### Coverage Target: **100%** for new fields in `src/extraction/models.py`

### Test Categories (6+ tests recommended)

1. **Field Initialization Tests** (3-4 tests)
   - Test that new fields have correct default values
   - Test that SourceSegment can be instantiated with new fields explicitly set
   - Test that mixing old and new field assignments works correctly

2. **to_dict() Tests** (2-3 tests)
   - Test that to_dict() includes all 6 new fields
   - Test that default values are correctly represented in dict
   - Test that explicitly set values are correctly represented

3. **Type Validation Tests** (optional but recommended)
   - Verify Optional[float] fields accept None
   - Verify int fields default to 0 not None

### Known Edge Cases to Test

- SourceSegment with only required fields (new fields should use defaults)
- SourceSegment with all new fields explicitly set
- to_dict() output with richness_score = 10.0 (max value)
- to_dict() output with metric_density = 0.0 (empty segment)

## Acceptance Criteria

- [x] 6 new fields added to SourceSegment with correct types and defaults
- [x] `to_dict()` method includes all 6 new fields
- [x] All new fields are Optional or have appropriate defaults
- [x] **6+ unit tests** covering field initialization and to_dict() (14 tests added)
- [x] All existing tests still pass (no regressions)
- [x] `mypy src/extraction/models.py --strict` passes
- [x] Field names match exactly: `metric_density`, `distinct_metric_count`, `contains_temporal_trend`, `contains_cohort_breakdown`, `image_count`, `richness_score`
- [ ] Documentation strings updated for new fields (optional but encouraged)

## Do NOT

- Modify `src/extraction/extraction_pipeline.py` (Task G3 handles database INSERT)
- Create SQL migration files (Task G2 handles that)
- Add any logic for computing field values (Tasks G4-G8 handle that)
- Change signatures or behavior of existing methods
- Add dependencies on other modules
- Modify the database schema (that's Task G2)

## Verification Commands

```bash
# Run new tests (create test file if needed)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_models.py -v

# Check coverage for models.py
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_models.py \
  --cov=src/extraction/models --cov-report=term-missing

# Type safety check
mypy src/extraction/models.py --strict

# Run all extraction tests to verify no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q

# Quick smoke test - verify SourceSegment can be instantiated
python3 -c "from src.extraction.models import SourceSegment; s = SourceSegment(filing_id=1, segment_type='paragraph'); print(s.richness_score, s.metric_density)"
```

## Integration Notes

**Downstream Dependencies** (what this enables):
- **G2** (SQL Migration) - Will add corresponding columns to `source_segments` table
- **G3** (Pipeline Insert) - Will persist these fields to database
- **G4** (SegmentEnricher) - Will compute `metric_density` and `distinct_metric_count`
- **G5-G7** - Will compute `contains_temporal_trend`, `contains_cohort_breakdown`, `image_count`
- **G8** - Will compute `richness_score`

**Mock Data Interface for Parallel Development**:
Once this task is complete, other developers can use this interface:
```python
segment = SourceSegment(
    filing_id=1,
    segment_type='paragraph',
    raw_text='Test text...',
    candidate_metric_ids=['cm_active_customers_total'],
    classifier_confidence=0.7,
    # New fields available (enricher will populate later):
    metric_density=None,  # Computed by G4
    distinct_metric_count=0,
    contains_temporal_trend=False,  # Computed by G5
    contains_cohort_breakdown=False,  # Computed by G6
    image_count=0,  # Computed by G7
    richness_score=None,  # Computed by G8
)
```

## Completion Checklist

- [x] Mark G1 as complete in `docs/GOLDMINE_IMPROVEMENT_PLAN.md`
- [x] Commit changes with message: `G1: Add richness metadata fields to SourceSegment`
- [x] G2, G3, G4, and G10 are now unblocked

## Reference

- **Issue source**: GOLDMINE_IMPROVEMENT_PLAN.md - Task G1
- **Dependencies**: None
- **Unblocks**: G2 (SQL Migration), G3 (Pipeline Insert), G4 (SegmentEnricher), G10 (Classifier Bonuses - independent but uses same fields conceptually)

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)

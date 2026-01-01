# WORKER PROMPT: Task EA-2 - Create Unified CandidateDetector

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EA-2
TASK NAME:     Create Unified CandidateDetector for extraction and review
WORKSTREAM:    Optional Architecture (Phase 2)
SOURCE:        docs/archive/improvement-plans-completed/EXTRACTION_IMPROVEMENT_PLAN.md
STATUS:        🟡 PENDING
TIME ESTIMATE: 6-8 hours (design 90 min, implementation 240 min, testing 120 min)
RISK LEVEL:    MEDIUM - Changes detection logic used by multiple modules
TASK SIZE:     L (4-8 hours)
DEPENDS ON:    EA-1 ✅ (StructureParser module)
UNLOCKS:       None (architectural improvement)
BLOCKS:        None
PARALLEL WITH: EA-3, GR-15, GR-18
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create a unified CandidateDetector class that consolidates metric detection logic currently duplicated between `CandidateGenerator` (review module) and `ValueExtractor` (extraction module), using StructureParser from EA-1 for consistent table-aware detection.

**Business Rationale**: The codebase currently has two separate detection pipelines that evolved independently:
- `CandidateGenerator` in `src/review/` with sophisticated filters (TableRowParser, FalsePositiveFilter)
- `ValueExtractor` in `src/extraction/` which was retrofitted with filters in EI-3/EI-4

This duplication causes maintenance burden and risks divergence in detection quality. A unified CandidateDetector provides:
- Single source of truth for metric detection logic
- Consistent filtering across extraction and review
- Easier testing and maintenance

**Current Behavior**: Two parallel detection implementations with overlapping but not identical logic.

**Desired Behavior**: One CandidateDetector class used by both extraction and review modules.

## Prerequisites

- EA-1 complete (StructureParser module for DOM position tracking)
- Understanding of EI-3, EI-4 implementations (filter integration)
- Understanding of review module's CandidateGenerator

## Files to Create

1. **`src/extraction/candidate_detector.py`** - Unified detection class
2. **`tests/unit/extraction/test_candidate_detector.py`** - Comprehensive tests

## Files to Modify

1. **`src/extraction/value_extractor.py`** - Integrate CandidateDetector (optional, can be Phase 2)
2. **`src/review/candidate_generator.py`** - Delegate to CandidateDetector (optional, can be Phase 2)

## Files to Read (Context Only)

- `src/extraction/structure_parser.py` - EA-1 StructureParser to use
- `src/review/candidate_generator.py` - Current detection logic to consolidate
- `src/review/keyword_matching.py` - Keyword matching logic
- `src/review/false_positive_filter.py` - FalsePositiveFilter to integrate
- `src/review/table_structure.py` - TableRowParser (may be replaced by StructureParser)
- `src/extraction/value_extractor.py` - Current extraction detection to consolidate

## Implementation Requirements

### Core Functionality

1. **CandidateDetector Class**

   ```python
   from dataclasses import dataclass
   from decimal import Decimal
   from typing import Optional

   @dataclass
   class DetectedCandidate:
       """A detected metric candidate with position info."""
       keyword: str
       keyword_position: int
       value: Decimal
       value_position: int
       unit: Optional[str]
       confidence: float
       same_row: bool  # True if keyword and value in same table row
       same_cell: bool  # True if keyword and value in same cell
       raw_text: str  # Surrounding context

   class CandidateDetector:
       """Unified metric candidate detection for extraction and review."""

       def __init__(
           self,
           use_false_positive_filter: bool = True,
           use_row_validation: bool = True,
           keywords: Optional[list[str]] = None,
       ):
           self.use_fp_filter = use_false_positive_filter
           self.use_row_validation = use_row_validation
           self.keywords = keywords or DEFAULT_KEYWORDS
           self._fp_filter = FalsePositiveFilter() if use_false_positive_filter else None

       def detect(
           self,
           text: str,
           html: Optional[str] = None,
           segment_type: str = "paragraph",
       ) -> list[DetectedCandidate]:
           """
           Detect metric candidates in text.

           Args:
               text: The text content to analyze
               html: Optional HTML for structure-aware detection
               segment_type: Type of segment (paragraph, table, etc.)

           Returns:
               List of detected candidates with positions and confidence
           """
           ...

       def detect_in_segment(self, segment: dict) -> list[DetectedCandidate]:
           """Convenience method to detect from segment dict."""
           return self.detect(
               text=segment.get("raw_text", ""),
               html=segment.get("raw_html"),
               segment_type=segment.get("segment_type", "paragraph"),
           )
   ```

2. **Detection Pipeline**
   - Parse text to find numbers (using NumberParser from review module)
   - Match keywords near numbers
   - Apply FalsePositiveFilter to reject pages, dates, years
   - Use StructureParser for table-aware row validation
   - Calculate confidence based on proximity and context

3. **Row Validation Integration**
   - Use EA-1's StructureParser.are_in_same_row() for table segments
   - Fall back to text-based heuristics for non-table segments
   - Reject cross-row keyword-value matches in tables

4. **False Positive Filtering**
   - Integrate existing FalsePositiveFilter from review module
   - Apply to all detected numbers before creating candidates
   - Preserve reason codes for debugging

5. **Keyword Matching**
   - Support configurable keyword lists
   - Use existing METRIC_KEYWORDS from keyword_matching.py
   - Calculate proximity-based confidence

### Error Handling

- **Missing HTML**: Proceed without row validation, log warning
- **Parser errors**: Catch BeautifulSoup exceptions, fall back to text-only
- **Empty segments**: Return empty list, no errors
- **Invalid numbers**: Filter out NaN/Inf values

### Performance Requirements

- Detect candidates in 10KB text in < 100ms
- Support batch detection for multiple segments
- Minimize memory allocation (reuse parsers)

### Medium Risk Precautions

- [ ] Create feature flag for gradual rollout: `use_unified_detector = True`
- [ ] Add integration test covering rollback scenario
- [ ] Do NOT replace existing detection in Phase 1 (create new class only)
- [ ] Test against known filings before integration

### Rollback Procedure

1. Set `use_unified_detector = False` in config
2. Modules revert to original detection logic
3. Verify with: `pytest tests/unit/extraction/test_candidate_detector.py`

## Test Requirements

### Coverage Target: **≥90%** for `src/extraction/candidate_detector.py`

### Test Categories (30+ tests)

1. **Basic Detection** (8-10 tests)
   - Single keyword-value pair detected
   - Multiple candidates in same text
   - Numbers without keywords rejected
   - Keywords without numbers rejected
   - Empty text returns empty list

2. **False Positive Filtering** (6-8 tests)
   - Page numbers filtered (e.g., "page 23")
   - Years filtered (1990-2100)
   - Dates filtered ("January 31, 2024")
   - Measurement units filtered ("24-hour period")
   - TOC references filtered

3. **Table-Aware Detection** (8-10 tests)
   - Keywords and values in same row accepted
   - Cross-row keyword-value matches rejected
   - Same-cell detection works
   - Non-table segments handle gracefully
   - Missing HTML handled with fallback

4. **Confidence Scoring** (4-5 tests)
   - Close proximity increases confidence
   - Same cell increases confidence
   - Definition language decreases confidence
   - Unit presence affects confidence

5. **Integration with StructureParser** (4-5 tests)
   - StructureParser used when HTML available
   - Position mapping correct
   - Row boundaries respected
   - Edge cases (empty cells, merged cells)

### Known Edge Cases to Test

- Numbers in footnotes
- Percentages vs absolute numbers
- Negative numbers
- Numbers with commas/periods (localization)
- Very large tables (100+ rows)

## Acceptance Criteria

- [ ] `src/extraction/candidate_detector.py` created with CandidateDetector class
- [ ] DetectedCandidate dataclass with all required fields
- [ ] `detect()` method returns list of candidates with positions
- [ ] FalsePositiveFilter integrated and filtering correctly
- [ ] StructureParser used for table-aware row validation
- [ ] 30+ unit tests with ≥90% coverage
- [ ] `mypy src/extraction/candidate_detector.py --strict` passes
- [ ] Performance: < 100ms for 10KB text
- [ ] Feature flag for gradual rollout documented
- [ ] All existing tests still pass
- [ ] NO integration with existing modules yet (Phase 1 only creates class)

## Do NOT

- Replace detection in `value_extractor.py` (that's Phase 2 integration)
- Replace detection in `candidate_generator.py` (that's Phase 2 integration)
- Modify existing filter classes (reuse as-is)
- Add new dependencies beyond what's in requirements.txt
- Over-engineer confidence scoring (start simple)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_candidate_detector.py -v --tb=short

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_candidate_detector.py \
  --cov=src/extraction/candidate_detector --cov-report=term-missing

# Type safety check
mypy src/extraction/candidate_detector.py --strict

# Verify StructureParser integration
python3 -c "
from src.extraction.candidate_detector import CandidateDetector, DetectedCandidate

html = '''
<table>
  <tr><td>Revenue</td><td>100 million</td></tr>
  <tr><td>Profit</td><td>50 million</td></tr>
</table>
'''
text = 'Revenue [CELL] 100 million [ROW] Profit [CELL] 50 million'

detector = CandidateDetector()
candidates = detector.detect(text=text, html=html, segment_type='table')
print(f'Found {len(candidates)} candidates')
for c in candidates:
    print(f'  {c.keyword}: {c.value} (same_row={c.same_row})')
"

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ tests/unit/review/ --no-cov -q
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# src/extraction/candidate_detector.py
"""
Unified candidate detection for extraction and review.

This module consolidates metric detection logic from:
- src/review/candidate_generator.py
- src/extraction/value_extractor.py

Uses StructureParser (EA-1) for table-aware detection.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import re

from src.extraction.structure_parser import StructureParser
from src.review.false_positive_filter import FalsePositiveFilter
from src.review.number_parsing import NumberParser, NumberMatch


@dataclass
class DetectedCandidate:
    """A detected metric candidate with position info."""
    keyword: str
    keyword_position: int
    value: Decimal
    value_position: int
    unit: Optional[str]
    confidence: float
    same_row: bool
    same_cell: bool
    raw_text: str


# Default keywords from existing implementations
DEFAULT_KEYWORDS = [
    "revenue", "users", "customers", "subscribers", "dau", "mau", "arpu",
    "gmv", "mrr", "arr", "retention", "conversion", "engagement",
]


class CandidateDetector:
    """Unified metric candidate detection."""

    MAX_KEYWORD_DISTANCE = 100  # Max chars between keyword and value

    def __init__(
        self,
        use_false_positive_filter: bool = True,
        use_row_validation: bool = True,
        keywords: Optional[list[str]] = None,
    ):
        self.use_fp_filter = use_false_positive_filter
        self.use_row_validation = use_row_validation
        self.keywords = keywords or DEFAULT_KEYWORDS
        self._fp_filter = FalsePositiveFilter() if use_false_positive_filter else None
        self._number_parser = NumberParser()

    def detect(
        self,
        text: str,
        html: Optional[str] = None,
        segment_type: str = "paragraph",
    ) -> list[DetectedCandidate]:
        """Detect metric candidates in text."""
        if not text or not text.strip():
            return []

        # Parse structure if HTML available and segment is table
        parser = None
        if html and segment_type == "table":
            try:
                parser = StructureParser(html)
            except Exception:
                parser = None

        # Find all numbers in text
        numbers = self._number_parser.parse(text)

        # Apply false positive filter
        if self._fp_filter:
            numbers = [
                n for n in numbers
                if not self._fp_filter.is_false_positive(text, n)[0]
            ]

        # Find keywords
        keyword_positions = self._find_keywords(text)

        # Match keywords to numbers
        candidates = []
        for num in numbers:
            for kw, kw_pos in keyword_positions:
                if self._is_valid_match(num, kw_pos, text, parser):
                    same_row = self._check_same_row(num.start, kw_pos, parser)
                    same_cell = self._check_same_cell(num.start, kw_pos, parser)
                    confidence = self._calculate_confidence(
                        num, kw_pos, same_row, same_cell
                    )

                    candidates.append(DetectedCandidate(
                        keyword=kw,
                        keyword_position=kw_pos,
                        value=num.value,
                        value_position=num.start,
                        unit=num.unit,
                        confidence=confidence,
                        same_row=same_row,
                        same_cell=same_cell,
                        raw_text=text[max(0, kw_pos-20):min(len(text), num.end+20)],
                    ))

        return candidates

    def _find_keywords(self, text: str) -> list[tuple[str, int]]:
        """Find all keyword positions in text."""
        text_lower = text.lower()
        results = []
        for kw in self.keywords:
            for match in re.finditer(rf"\b{re.escape(kw)}\b", text_lower):
                results.append((kw, match.start()))
        return results

    def _is_valid_match(
        self,
        num: NumberMatch,
        kw_pos: int,
        text: str,
        parser: Optional[StructureParser],
    ) -> bool:
        """Check if keyword-number pair is a valid match."""
        distance = abs(num.start - kw_pos)
        if distance > self.MAX_KEYWORD_DISTANCE:
            return False

        # For tables, require same row
        if parser and self.use_row_validation:
            if not parser.are_in_same_row(kw_pos, num.start):
                return False

        return True

    def _check_same_row(
        self, pos1: int, pos2: int, parser: Optional[StructureParser]
    ) -> bool:
        """Check if positions are in same row."""
        if parser:
            return parser.are_in_same_row(pos1, pos2)
        return True  # Assume same row for non-table

    def _check_same_cell(
        self, pos1: int, pos2: int, parser: Optional[StructureParser]
    ) -> bool:
        """Check if positions are in same cell."""
        if parser:
            return parser.are_in_same_cell(pos1, pos2)
        return True  # Assume same cell for non-table

    def _calculate_confidence(
        self,
        num: NumberMatch,
        kw_pos: int,
        same_row: bool,
        same_cell: bool,
    ) -> float:
        """Calculate confidence score for candidate."""
        base = 0.5
        distance = abs(num.start - kw_pos)

        # Proximity bonus
        if distance < 20:
            base += 0.3
        elif distance < 50:
            base += 0.15

        # Structure bonuses
        if same_cell:
            base += 0.15
        elif same_row:
            base += 0.05

        return min(1.0, base)
```
</details>

## Expected Impact

**Before EA-2**:
- Two separate detection implementations
- Duplicated filter integration code
- Risk of divergence in detection quality
- Harder to maintain and test

**After EA-2**:
- Single CandidateDetector class
- Consistent filtering across modules
- Uses EA-1 StructureParser for accuracy
- Easier maintenance and testing
- Foundation for further consolidation

## Integration Plan (Post-EA-2)

After EA-2 creates the CandidateDetector class:

1. **Phase 2a**: Integrate into `value_extractor.py` (separate task)
2. **Phase 2b**: Integrate into `candidate_generator.py` (separate task)
3. **Phase 2c**: Deprecate duplicate detection code (after validation)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4

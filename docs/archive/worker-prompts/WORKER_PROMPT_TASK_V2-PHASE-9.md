# WORKER PROMPT: Task V2-PHASE-9 - Fact Construction Stage

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-9
TASK NAME:     Implement Fact Construction Stage for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        V2_IMPLEMENTATION_ROADMAP.md - Phase 9
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (M task)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Transformation stage, no external dependencies
TASK SIZE:     M
DEPENDS ON:    V2-PHASE-7 (BoundValue), V2-PHASE-8 (Period Inference)
UNLOCKS:       V2-PHASE-10 (Deduplication)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create the Fact Construction Stage (Stage 9) for the V2 extraction pipeline. This stage transforms `BoundValue` objects (with period information from Stage 8) into complete `MetricFact` objects with confidence scores and evidence packs.

**Business Rationale**: MetricFact is the primary output of the extraction pipeline - a fully-attributed metric value with audit-grade provenance. This stage assembles all the pieces collected by prior stages into the final data structure.

**Current Behavior**: `FactConstructionStage` in `pipeline.py` is a stub that returns empty results.

**Desired Behavior**: Stage processes all bound values, computes confidence scores, generates evidence packs, and populates `context.facts` with complete `MetricFact` objects.

## Prerequisites

- V2-PHASE-7 (Value Binding): Provides `context.bound_values` with value, unit, binding info
- V2-PHASE-8 (Period Inference): Provides period_type, period_start, period_end on BoundValue
- Understanding of `MetricFact` and `EvidencePack` dataclasses in `models.py`

## Files to Create

1. **`src/extraction_v2/stages/fact_construction.py`** - FactConstructionStage implementation (~150-200 lines)
2. **`tests/unit/extraction_v2/test_fact_construction.py`** - Unit tests (~200-300 lines)

## Files to Modify

1. **`src/extraction_v2/stages/__init__.py`** - Export FactConstructionStage
2. **`src/extraction_v2/pipeline.py`** - Replace stub with import from stages module

## Files to Read (Context Only)

- `src/extraction_v2/models.py` - MetricFact, EvidencePack, BoundValue, SourceLocator structures
- `src/extraction_v2/stages/period_inference.py` - Stage implementation pattern
- `src/extraction_v2/stages/value_binding.py` - Stage implementation pattern
- `src/extraction_v2/pipeline.py` - PipelineContext, StageResult structures

## Implementation Requirements

### Core Functionality

1. **FactConstructionStage Class**
   - `__init__()` with optional configuration parameters
   - `process(context: PipelineContext) -> StageResult` following stage protocol

2. **BoundValue → MetricFact Transformation**
   For each `BoundValue` in `context.bound_values`:
   - Create new `MetricFact` with unique `fact_id`
   - Set `doc_id` from `context.document.doc_id`
   - Set `canonical_metric_id` by looking up the candidate (requires candidate lookup)
   - Copy value fields: `value`, `value_raw`, `unit`
   - Copy period fields: `period_type`, `period_start`, `period_end`
   - Set `source_type` based on `BoundValue.source_locator`
   - Copy `source_locator` from `BoundValue`
   - Generate `evidence_pack`
   - Compute `confidence` score
   - Set `extraction_method` (EXACT_MATCH for keyword-based)
   - Initialize `requires_review = True` (Validation stage will adjust)

3. **Confidence Scoring Logic**
   ```python
   # Base from binding confidence
   confidence = bound_value.binding_confidence

   # Section bonuses (need segment lookup)
   if section_type == SectionType.MDA:
       confidence += 0.1  # High-value section
   elif section_type == SectionType.BUSINESS:
       confidence += 0.05

   # Source type penalties
   if source_type == SourceType.OCR_TABLE:
       confidence -= 0.1
   if source_type == SourceType.CHART:
       confidence -= 0.05  # Charts are less reliable

   # Period confidence factor (weighted blend)
   confidence = confidence * 0.8 + bound_value.period_confidence * 0.2

   # Period ambiguity penalty
   if bound_value.period_ambiguous:
       confidence -= 0.15

   # Clamp to [0, 1]
   confidence = max(0.0, min(1.0, confidence))
   ```

4. **EvidencePack Generation**

   For **table sources** (`source_locator.table_id` is set):
   - `snippet_html`: Generate highlighted HTML table excerpt showing the cell
   - `header_path`: From table column headers
   - `stub_path`: From table row stubs
   - `raw_value_text`: From `BoundValue.value_raw`

   For **text sources** (`source_type == TEXT`):
   - `snippet_html`: Text with highlighted value
   - `context_before`: 50 words before the value
   - `context_after`: 50 words after the value
   - `raw_value_text`: From `BoundValue.value_raw`

   For **chart sources** (future, stub acceptable):
   - `screenshot_path`: Path to chart image (if available)
   - `raw_value_text`: From `BoundValue.value_raw`

5. **Source Type Determination**
   Based on `source_locator` contents:
   - Has `table_id` and no `img_id` → `SourceType.HTML_TABLE`
   - Has `table_id` and `img_id` → `SourceType.OCR_TABLE`
   - Has `img_id` and no `table_id` → `SourceType.CHART`
   - Otherwise → `SourceType.TEXT`

6. **Candidate Lookup**
   Build a lookup dict from `context.candidates` by `candidate_id` to retrieve:
   - `metric_id` → `canonical_metric_id`
   - `section_type` → for confidence scoring

### Error Handling

- **Missing candidate for bound value**: Log warning, use empty metric_id
- **Missing segment/table for evidence**: Generate minimal evidence pack
- **Individual fact errors**: Log and continue to next bound value

### Performance Requirements

- Process 500 bound values in <2 seconds
- Use lookup dicts for segments/tables/candidates (O(1) access)

## Test Requirements

### Coverage Target: **≥80%** for `fact_construction.py`

### Test Categories (15+ tests recommended)

1. **Basic Transformation** (3-4 tests)
   - Single BoundValue → MetricFact with all fields populated
   - Multiple BoundValues → multiple MetricFacts
   - Empty bound_values returns success with zero facts

2. **Confidence Scoring** (4-5 tests)
   - Base confidence from binding_confidence
   - MDA section bonus (+0.1)
   - BUSINESS section bonus (+0.05)
   - OCR_TABLE penalty (-0.1)
   - Period ambiguity penalty (-0.15)
   - Confidence clamped to [0, 1]

3. **EvidencePack Generation** (4-5 tests)
   - Table source: header_path and stub_path populated
   - Text source: context_before and context_after populated
   - snippet_html generated for table sources
   - raw_value_text always populated

4. **Source Type Determination** (3-4 tests)
   - HTML_TABLE when table_id present
   - TEXT when only segment_id present
   - CHART when img_id present

5. **Integration** (2-3 tests)
   - Full stage execution with mock context
   - StageResult metadata populated correctly

### Known Edge Cases to Test

- BoundValue with missing candidate_id → fallback behavior
- BoundValue with period_ambiguous=True → confidence penalty applied
- Multiple BoundValues from same candidate → separate facts created
- BoundValue with minimal source_locator → minimal evidence pack

## Acceptance Criteria

- [ ] AC-1: `src/extraction_v2/stages/fact_construction.py` exists
- [ ] AC-2: `FactConstructionStage.process()` transforms `BoundValue` → `MetricFact`
- [ ] AC-3: Confidence scoring: base from binding + section bonus + penalties
- [ ] AC-4: `EvidencePack` generated with snippet_html for table sources
- [ ] AC-5: `EvidencePack` generated with context_before/after for text sources
- [ ] AC-6: `source_type` correctly set (HTML_TABLE, TEXT, CHART)
- [ ] AC-7: `source_locator` populated from bound value
- [ ] AC-8: Pipeline integration: stage exported in `__init__.py`
- [ ] AC-9: Tests in `tests/unit/extraction_v2/test_fact_construction.py`
- [ ] AC-10: Coverage ≥80% for new module
- [ ] AC-11: `mypy --strict` passes on new module
- [ ] AC-12: `ruff check` passes

## Do NOT

- Modify `config/metric_keywords.yaml` (not relevant to this stage)
- Modify V1 modules
- Add LLM calls - this stage is rule-based only
- Change existing stage implementations (except removing stub from pipeline.py)
- Add database persistence (that's Phase 12)
- Implement screenshot capture for evidence (stub path is acceptable)

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_fact_construction.py -v

# Check coverage (must be ≥80%)
pytest tests/unit/extraction_v2/test_fact_construction.py \
  --cov=src/extraction_v2/stages/fact_construction --cov-report=term-missing

# Type safety check
mypy src/extraction_v2/stages/fact_construction.py --strict

# Lint
ruff check src/extraction_v2/stages/fact_construction.py

# Verify pipeline still works
pytest tests/unit/extraction_v2/ -v -q

# Full regression test
pytest tests/unit/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task V2-PHASE-9: Fact Construction Stage
# Run: bash verify_v2_phase_9.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task V2-PHASE-9: Fact Construction Stage"
echo "═══════════════════════════════════════════════════════════════"

# AC-1: File exists
echo "✓ Checking: fact_construction.py exists..."
test -f src/extraction_v2/stages/fact_construction.py

# AC-8: Stage exports
echo "✓ Checking: FactConstructionStage exported..."
python3 -c "from src.extraction_v2.stages import FactConstructionStage"

# AC-9: Test file exists
echo "✓ Checking: test file exists..."
test -f tests/unit/extraction_v2/test_fact_construction.py

# AC-2: Pipeline imports work
echo "✓ Checking: Pipeline uses FactConstructionStage from stages..."
python3 -c "from src.extraction_v2.pipeline import V2Pipeline; p = V2Pipeline()"

# AC-10: Test coverage >= 80%
echo "✓ Checking: Test coverage ≥ 80%..."
pytest tests/unit/extraction_v2/test_fact_construction.py \
  --cov=src/extraction_v2/stages/fact_construction \
  --cov-report=term --cov-fail-under=80 -q

# AC-11: Type safety
echo "✓ Checking: mypy passes..."
mypy src/extraction_v2/stages/fact_construction.py --strict

# AC-12: Lint passes
echo "✓ Checking: ruff passes..."
ruff check src/extraction_v2/stages/fact_construction.py

# Full V2 test suite
echo "✓ Running V2 extraction tests..."
pytest tests/unit/extraction_v2/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task V2-PHASE-9!"
echo "═══════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size.**

| Task Size | Evaluation Depth |
|-----------|------------------|
| M | Standard: code quality, test coverage, architecture alignment |

After verification passes but BEFORE committing, perform this evaluation:

### 1. Code Quality Review
- [ ] No linting issues or type errors beyond what was verified
- [ ] DRY principle followed (no unnecessary duplication)
- [ ] Naming conventions match project standards
- [ ] Error handling is appropriate (not over/under-engineered)

### 2. Test Coverage Assessment
- [ ] Edge cases from requirements are covered
- [ ] Negative test cases exist (what should fail)
- [ ] No obvious untested scenarios

### 3. Architecture Alignment
- [ ] Solution follows patterns documented in CLAUDE.md
- [ ] No violations of design decisions (rule-based first, conservative classification)
- [ ] Changes are minimal and focused (no over-engineering)

### 4. Identify Improvements
Document any potential improvements discovered during evaluation:
- Performance optimizations
- Additional edge cases to handle
- Code simplifications

### 5. User Approval (REQUIRED)
**STOP and ask the user before committing.**

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
"""V2 Fact Construction Stage."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    BoundValue,
    EvidencePack,
    ExtractionMethod,
    MetricFact,
    SectionType,
    SourceType,
)

if TYPE_CHECKING:
    from src.extraction_v2.models import MetricCandidate, Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


# Confidence adjustment constants
MDA_SECTION_BONUS: float = 0.10
BUSINESS_SECTION_BONUS: float = 0.05
OCR_TABLE_PENALTY: float = 0.10
CHART_PENALTY: float = 0.05
PERIOD_AMBIGUITY_PENALTY: float = 0.15


class FactConstructionStage:
    """Stage 9: Fact Construction."""

    def __init__(self) -> None:
        pass

    def process(self, context: PipelineContext) -> StageResult:
        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        # Build lookups
        candidate_lookup = {c.candidate_id: c for c in context.candidates}
        segment_lookup = {s.segment_id: s for s in context.segments}
        table_lookup = {t.table_id: t for t in context.tables}

        # Process bound values
        for bv in context.bound_values:
            try:
                fact = self._construct_fact(
                    bv, candidate_lookup, segment_lookup, table_lookup, context
                )
                context.facts.append(fact)
            except Exception as e:
                errors.append(f"Error constructing fact for {bv.bound_value_id}: {e}")

        return self._make_result(start_time, len(context.bound_values), len(context.facts), errors, warnings)

    def _construct_fact(
        self,
        bv: BoundValue,
        candidate_lookup: dict[str, MetricCandidate],
        segment_lookup: dict[str, Segment],
        table_lookup: dict[str, Table],
        context: PipelineContext,
    ) -> MetricFact:
        # Look up candidate for metric_id
        candidate = candidate_lookup.get(bv.candidate_id)
        metric_id = candidate.metric_id if candidate else ""

        # Determine source type
        source_type = self._determine_source_type(bv)

        # Compute confidence
        confidence = self._compute_confidence(bv, candidate, source_type)

        # Generate evidence pack
        evidence = self._generate_evidence(bv, segment_lookup, table_lookup)

        return MetricFact(
            doc_id=context.document.doc_id if context.document else "",
            canonical_metric_id=metric_id,
            value=bv.value,
            value_raw=bv.value_raw,
            unit=bv.unit,
            period_type=bv.period_type,
            period_start=bv.period_start,
            period_end=bv.period_end,
            source_type=source_type,
            source_locator=bv.source_locator,
            evidence_pack=evidence,
            confidence=confidence,
            extraction_method=ExtractionMethod.EXACT_MATCH,
            requires_review=True,
        )

    def _determine_source_type(self, bv: BoundValue) -> SourceType:
        loc = bv.source_locator
        if loc.table_id and not loc.img_id:
            return SourceType.HTML_TABLE
        elif loc.table_id and loc.img_id:
            return SourceType.OCR_TABLE
        elif loc.img_id and not loc.table_id:
            return SourceType.CHART
        return SourceType.TEXT

    def _compute_confidence(
        self,
        bv: BoundValue,
        candidate: MetricCandidate | None,
        source_type: SourceType,
    ) -> float:
        confidence = bv.binding_confidence

        # Section bonuses
        if candidate:
            if candidate.section_type == SectionType.MDA:
                confidence += MDA_SECTION_BONUS
            elif candidate.section_type == SectionType.BUSINESS:
                confidence += BUSINESS_SECTION_BONUS

        # Source penalties
        if source_type == SourceType.OCR_TABLE:
            confidence -= OCR_TABLE_PENALTY
        elif source_type == SourceType.CHART:
            confidence -= CHART_PENALTY

        # Period factors
        confidence = confidence * 0.8 + bv.period_confidence * 0.2
        if bv.period_ambiguous:
            confidence -= PERIOD_AMBIGUITY_PENALTY

        return max(0.0, min(1.0, confidence))

    def _generate_evidence(
        self,
        bv: BoundValue,
        segment_lookup: dict[str, Segment],
        table_lookup: dict[str, Table],
    ) -> EvidencePack:
        loc = bv.source_locator
        header_path: list[str] = []
        stub_path: list[str] = []
        context_before = ""
        context_after = ""
        snippet_html = ""

        if loc.table_id:
            table = table_lookup.get(loc.table_id)
            if table and loc.cell_col is not None:
                header_path = table.get_header_path(loc.cell_col)
            if table and loc.cell_row is not None:
                stub_path = table.get_stub_path(loc.cell_row)
            snippet_html = f"<mark>{bv.value_raw}</mark>"

        if loc.segment_id and not loc.table_id:
            segment = segment_lookup.get(loc.segment_id)
            if segment and loc.text_span:
                start, end = loc.text_span
                text = segment.text
                context_before = text[max(0, start - 200):start].strip()
                context_after = text[end:end + 200].strip()
            snippet_html = f"<mark>{bv.value_raw}</mark>"

        return EvidencePack(
            snippet_html=snippet_html,
            header_path=header_path,
            stub_path=stub_path,
            context_before=context_before,
            context_after=context_after,
            raw_value_text=bv.value_raw,
        )
```
</details>

## Reference

- **Issue source**: V2_IMPLEMENTATION_ROADMAP.md Phase 9
- **Dependencies**: V2-PHASE-7 (BoundValue), V2-PHASE-8 (Period Inference)
- **Related**: models.py (MetricFact, EvidencePack structures)

---

**Last Updated**: 2026-02-04
**Format Version**: 2.6

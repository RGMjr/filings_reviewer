# WORKER PROMPT: Task V2-PHASE-7 - Value Binding Stage

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-7
TASK NAME:     Implement Value Binding Stage for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        V2_IMPLEMENTATION_ROADMAP.md - Phase 7
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-4 hours (L task: table binding 60 min, text binding 60 min, tests 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Rule-based extraction, no data format changes
TASK SIZE:     L
DEPENDS ON:    V2-PHASE-3 (tables with header_path/stub_path), V2-PHASE-6 (candidates)
UNLOCKS:       V2-PHASE-8 (period inference), V2-PHASE-9 (fact construction)
BLOCKS:        None
PARALLEL WITH: V2-PHASE-4, V2-PHASE-5 (image pipeline)
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create the Value Binding Stage (Stage 7) for the V2 extraction pipeline. This stage links metric keyword candidates from Stage 6 to their numeric values, producing `BoundValue` objects that associate each candidate with its extracted value, unit, and binding confidence.

**Business Rationale**: Value binding is the critical step that converts keyword mentions into actionable data. A metric keyword without a bound value is useless - this stage bridges candidate detection with fact construction.

**Current Behavior**: `ValueBindingStage` in `pipeline.py` is a stub that returns empty results.

**Desired Behavior**: Stage processes all candidates, finds associated numeric values using structural rules (table cell binding, text proximity), and produces BoundValue objects for downstream period inference and fact construction.

## Prerequisites

- V2-PHASE-3 (Table Reconstruction): Provides `context.tables` with `header_path`/`stub_path` per cell
- V2-PHASE-6 (Candidate Generation): Provides `context.candidates` with MetricCandidate objects
- Understanding of V1 `src/extraction/value_extractor.py` patterns

## Files to Create

1. **`src/extraction_v2/stages/value_binding.py`** - ValueBindingStage implementation (~200-300 lines)
2. **`tests/unit/extraction_v2/test_value_binding.py`** - Unit tests (~300-400 lines)

## Files to Modify

1. **`src/extraction_v2/pipeline.py`** - Replace stub with import
2. **`src/extraction_v2/stages/__init__.py`** - Export ValueBindingStage
3. **`src/extraction_v2/models.py`** - Add BoundValue dataclass (if not present)

## Files to Read (Context Only)

- `src/extraction/value_extractor.py` - V1 binding logic (reference for patterns)
- `src/extraction_v2/stages/candidate_generation.py` - Stage implementation pattern
- `src/extraction_v2/models.py` - MetricCandidate, Cell, Table structures
- `src/review/number_parsing.py` - Number parsing utilities (potential reuse)

## Implementation Requirements

### Core Functionality

1. **BoundValue Dataclass** (add to models.py if not present)
   - `bound_value_id`: UUID
   - `candidate_id`: Reference to MetricCandidate
   - `value`: float (parsed numeric value)
   - `value_raw`: str (original text, e.g., "$1.2M", "112%")
   - `unit`: Unit enum (PERCENT, CURRENCY, COUNT, RATIO)
   - `binding_type`: str ("table_header", "table_stub", "text_proximity", "chart_label")
   - `binding_confidence`: float 0.0-1.0
   - `source_locator`: SourceLocator (points to the value location, may differ from candidate)

2. **Table Binding** (highest priority)
   - For candidates where `source_locator.table_id` is set:
     - Find metric keyword in `header_path` → bind value from data cells in that column
     - Find metric keyword in `stub_path` → bind value from data cells in that row
   - Store the structural path that led to binding in evidence

3. **Text Binding** (fallback)
   - For candidates with `source_type == TEXT`:
     - Find numeric values within N words (default: 10) of the keyword match
     - Validate value is in same sentence/paragraph as keyword
     - Prefer values with units matching metric type (e.g., currency for revenue metrics)

4. **Chart Binding** (future - stub for now)
   - For candidates from chart sources, use labeled values from ChartData
   - **RULE**: Only use explicitly labeled values, NEVER interpolate from axis readings
   - Can be a stub returning empty for now (Phase 5 dependency)

5. **Binding Confidence Scoring**
   - Base: 0.6 for table binding, 0.4 for text binding
   - +0.2 if metric keyword is exact match in header_path/stub_path
   - +0.1 if value has explicit unit (e.g., "$" or "%")
   - -0.1 if value is ambiguous (multiple candidates in proximity)

6. **Number Parsing**
   - Handle comma separators: 1,234,567
   - Handle scale indicators: "million", "billion", "thousand"
   - Handle currency: $, €, £
   - Handle percentages: 112%, 1.5%
   - Consider reusing `src/review/number_parsing.py` patterns

### Error Handling

- **No value found for candidate**: Log warning, skip candidate (don't bind)
- **Ambiguous binding** (multiple values): Bind highest confidence, log warning
- **Unparseable value**: Log warning, skip
- **Individual binding errors**: Log and continue to next candidate

### Performance Requirements

- Process 500 candidates in <5 seconds
- Avoid re-parsing tables - use already-reconstructed Table objects from context

## Test Requirements

### Coverage Target: **≥90%** for `value_binding.py`

### Test Categories (20+ tests recommended)

1. **Table Binding - Header Path** (5-6 tests)
   - Metric in column header → bind data cells
   - Multi-level headers (metric in 2nd header row)
   - No match when metric not in headers
   - Handle empty cells gracefully

2. **Table Binding - Stub Path** (4-5 tests)
   - Metric in row stub → bind data cells
   - Multi-column stubs
   - Combined header+stub context

3. **Text Binding** (5-6 tests)
   - Value within proximity of keyword
   - Value in same sentence
   - No binding when value too far
   - Multiple values - pick best
   - Case insensitive matching

4. **Number Parsing** (4-5 tests)
   - Currency values ($1.2M, $1,234)
   - Percentages (112%, 1.5%)
   - Scale indicators (million, billion)
   - Plain integers with commas

5. **Confidence Scoring** (3-4 tests)
   - Table binding higher than text
   - Exact match bonus
   - Unit presence bonus

6. **Integration** (2-3 tests)
   - Full stage execution with mock context
   - Empty candidates returns success with zero bindings

### Known Edge Cases to Test

- Candidate in table header (not data cell) - should find value below
- Multiple metrics in same table row
- Percentage vs count ambiguity (100 vs 100%)
- Negative values (-5%, -$1.2M)
- Value spans table cell markers

## Acceptance Criteria

- [ ] `BoundValue` dataclass defined with required fields in models.py
- [ ] `ValueBindingStage` class with `process()` method following stage protocol
- [ ] Table binding via header_path implemented
- [ ] Table binding via stub_path implemented
- [ ] Text proximity binding implemented
- [ ] Chart binding stubbed (returns empty, logged as "not implemented")
- [ ] Number parsing handles currency, percentages, scale indicators
- [ ] Confidence scoring implemented per specification
- [ ] `bound_values` list populated in `context.bound_values`
- [ ] Stub in `pipeline.py` replaced with real import
- [ ] `stages/__init__.py` exports ValueBindingStage
- [ ] **20+ unit tests** covering all binding types
- [ ] **Test coverage ≥90%** for value_binding.py
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy src/extraction_v2/stages/value_binding.py --strict` passes

## Do NOT

- Modify `config/metric_keywords.yaml` (not relevant to this stage)
- Modify V1 modules (`value_extractor.py` is reference only)
- Add LLM calls - this stage is rule-based only
- Change existing stage implementations (ingestion, section_classification, table_reconstruction, candidate_generation)
- Add database persistence (that's Phase 12)
- Implement full chart binding (Phase 5 dependency - stub is acceptable)

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_value_binding.py -v

# Check coverage (must be ≥90%)
pytest tests/unit/extraction_v2/test_value_binding.py \
  --cov=src/extraction_v2/stages/value_binding --cov-report=term-missing

# Type safety check
mypy src/extraction_v2/stages/value_binding.py --strict

# Lint
ruff check src/extraction_v2/stages/value_binding.py

# Verify pipeline still works
pytest tests/unit/extraction_v2/ -v -q

# Full regression test
pytest tests/unit/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task V2-PHASE-7: Value Binding Stage
# Run: bash verify_v2_phase_7.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task V2-PHASE-7: Value Binding Stage"
echo "═══════════════════════════════════════════════════════════════"

# Criterion 1: File exists
echo "✓ Checking: value_binding.py exists..."
test -f src/extraction_v2/stages/value_binding.py

# Criterion 2: Test file exists
echo "✓ Checking: test file exists..."
test -f tests/unit/extraction_v2/test_value_binding.py

# Criterion 3: BoundValue dataclass exists
echo "✓ Checking: BoundValue dataclass defined..."
python3 -c "from src.extraction_v2.models import BoundValue"

# Criterion 4: Stage exports
echo "✓ Checking: ValueBindingStage exported..."
python3 -c "from src.extraction_v2.stages import ValueBindingStage"

# Criterion 5: Pipeline imports work
echo "✓ Checking: Pipeline imports ValueBindingStage..."
python3 -c "from src.extraction_v2.pipeline import V2Pipeline; p = V2Pipeline()"

# Criterion 6: Test coverage >= 90%
echo "✓ Checking: Test coverage ≥ 90%..."
pytest tests/unit/extraction_v2/test_value_binding.py \
  --cov=src/extraction_v2/stages/value_binding \
  --cov-report=term --cov-fail-under=90 -q

# Criterion 7: Type safety
echo "✓ Checking: mypy passes..."
mypy src/extraction_v2/stages/value_binding.py --strict

# Criterion 8: Lint passes
echo "✓ Checking: ruff passes..."
ruff check src/extraction_v2/stages/value_binding.py

# Criterion 9: Full V2 test suite
echo "✓ Running V2 extraction tests..."
pytest tests/unit/extraction_v2/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task V2-PHASE-7!"
echo "═══════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size.**

| Task Size | Evaluation Depth |
|-----------|------------------|
| L | Thorough: full checklist, comprehensive improvement search |

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
- [ ] Integration with existing code is tested

### 3. Architecture Alignment
- [ ] Solution follows patterns documented in CLAUDE.md
- [ ] No violations of design decisions (rule-based first, conservative classification)
- [ ] Changes are minimal and focused (no over-engineering)

### 4. Identify Improvements
Document any potential improvements discovered during evaluation:
- Performance optimizations
- Additional edge cases to handle
- Code simplifications
- Documentation updates needed

### 5. User Approval (REQUIRED)
**STOP and ask the user before committing.**

### 6-9. Standard completion steps
Follow template for commit, push, and documentation updates.

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
@dataclass
class BoundValue:
    """Value bound to a metric candidate."""
    bound_value_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    candidate_id: str = ""
    value: float | None = None
    value_raw: str = ""
    unit: Unit = Unit.OTHER
    binding_type: str = ""  # "table_header", "table_stub", "text_proximity"
    binding_confidence: float = 0.5
    source_locator: SourceLocator = field(default_factory=SourceLocator)


class ValueBindingStage:
    """Stage 7: Value Binding."""

    def __init__(self) -> None:
        self._number_pattern = re.compile(...)

    def process(self, context: PipelineContext) -> StageResult:
        # 1. Group candidates by source type
        # 2. Bind table candidates
        # 3. Bind text candidates
        # 4. Return StageResult
        pass

    def _bind_table_candidate(
        self, candidate: MetricCandidate, tables: list[Table]
    ) -> list[BoundValue]:
        # Find table, check header_path/stub_path, extract values
        pass

    def _bind_text_candidate(
        self, candidate: MetricCandidate, segments: list[Segment]
    ) -> list[BoundValue]:
        # Find numbers in proximity, validate same sentence
        pass
```
</details>

## Reference

- **Issue source**: V2_IMPLEMENTATION_ROADMAP.md Phase 7
- **Dependencies**: V2-PHASE-3 (tables), V2-PHASE-6 (candidates)
- **Related**: V1 value_extractor.py (reference for patterns)

---

**Last Updated**: 2026-02-03
**Format Version**: 2.6

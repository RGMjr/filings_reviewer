# WORKER PROMPT: Task V2-PHASE-6 - Candidate Generation Stage

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-6
TASK NAME:     Implement Candidate Generation Stage for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        V2_IMPLEMENTATION_ROADMAP.md - Phase 6
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (M task: stage impl 45 min, tests 45 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Reuses stable V1 modules, no data format changes
TASK SIZE:     M
DEPENDS ON:    V2-PHASE-3 (tables), V2-PHASE-1 (segments)
UNLOCKS:       V2-PHASE-7 (value binding)
BLOCKS:        None
PARALLEL WITH: V2-PHASE-4, V2-PHASE-5 (image pipeline)
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create the Candidate Generation Stage (Stage 6) for the V2 extraction pipeline. This stage scans all content (segments, table cells, OCR text) for metric keyword matches using the YAML taxonomy, applying exclusion patterns and false positive filtering to produce `MetricCandidate` objects.

**Business Rationale**: Candidate generation is the foundation of metric extraction - it identifies WHERE metrics might be mentioned before subsequent stages bind values. Reusing V1's battle-tested keyword configuration ensures consistency with existing production behavior.

**Current Behavior**: `CandidateGenerationStage` in `pipeline.py` is a stub that returns empty results.

**Desired Behavior**: Stage processes all segments and tables, finding metric keyword matches and creating candidates with source locators for downstream value binding.

## Prerequisites

- V2-PHASE-1 (Ingestion): Provides `context.segments` with text content
- V2-PHASE-3 (Table Reconstruction): Provides `context.tables` with cells containing `header_path`/`stub_path`
- V1 modules available for import: `keyword_config.py`, `false_positive_filter.py`, `number_parsing.py`

## Files to Create

1. **`src/extraction_v2/stages/candidate_generation.py`** - CandidateGenerationStage implementation (~150-200 lines)
2. **`tests/unit/extraction_v2/test_candidate_generation.py`** - Unit tests (~250-350 lines)

## Files to Modify

1. **`src/extraction_v2/pipeline.py`** - Replace stub with import
2. **`src/extraction_v2/stages/__init__.py`** - Export CandidateGenerationStage
3. **`src/extraction_v2/models.py`** - Add MetricCandidate dataclass (if not present)

## Files to Read (Context Only)

- `src/extraction/keyword_config.py` - YAML taxonomy loading (reuse directly)
- `src/review/false_positive_filter.py` - False positive detection (reuse directly)
- `src/review/number_parsing.py` - NumberParser for context (reference)
- `config/metric_keywords.yaml` - Understand keyword structure
- `src/extraction_v2/stages/table_reconstruction.py` - Pattern for stage implementation

## Implementation Requirements

### Core Functionality

1. **MetricCandidate Dataclass**
   - `candidate_id`: UUID
   - `metric_id`: String (e.g., "cm_arr")
   - `match_text`: The matched keyword text
   - `source_locator`: SourceLocator pointing to source
   - `source_type`: SourceType enum (HTML_TABLE, TEXT)
   - `confidence`: Float 0.0-1.0 (base confidence from match type)
   - `context_text`: Surrounding text for context (100 chars each side)

2. **Segment Scanning**
   - Iterate `context.segments` from pipeline context
   - For each segment, scan `segment.text` for keyword patterns
   - Use `get_metric_keywords()` from `src/extraction/keyword_config.py`
   - Create SourceLocator with `segment_id`, `dom_locator`, `text_span`
   - Store matched candidates in `context.candidates`

3. **Table Cell Scanning**
   - Iterate `context.tables` and their cells
   - Scan combined text: `cell.text + " ".join(cell.header_path) + " ".join(cell.stub_path)`
   - This catches metrics mentioned in headers/stubs, not just cell values
   - Create SourceLocator with `table_id`, `cell_row`, `cell_col`

4. **Filtering Pipeline**
   - Apply exclusion patterns per metric from `get_exclusion_patterns()`
   - Apply required_context filters from `get_required_context()` (e.g., revenue synonyms need cohort context)
   - Apply `FalsePositiveFilter` from `src/review/false_positive_filter.py` to filter years, dates, page refs
   - Only create candidates that pass all filters

5. **Confidence Scoring**
   - Base confidence 0.5 for standard pattern match
   - Bonus +0.1 for specific_pattern match (multi-word patterns)
   - Bonus +0.1 for table source (more structured)
   - Bonus +0.1 for MD&A or Business section context

### Error Handling

- **Invalid regex patterns**: Log warning, skip pattern
- **Missing keyword config**: Log error, return empty candidates (don't crash pipeline)
- **Individual segment errors**: Log and continue to next segment

### Performance Requirements

- Process 1000 segments in <5 seconds (regex matching is fast)
- Compile regex patterns once at stage initialization, not per-segment

## Test Requirements

### Coverage Target: **≥90%** for `candidate_generation.py`

### Test Categories (15+ tests recommended)

1. **Segment Scanning** (4-5 tests)
   - Finds keyword in simple paragraph
   - Multiple keywords in single segment
   - No match when keyword absent
   - Case-insensitive matching

2. **Table Cell Scanning** (3-4 tests)
   - Finds keyword in cell text
   - Finds keyword in header_path
   - Finds keyword in stub_path
   - Creates correct table source locator

3. **Filtering** (4-5 tests)
   - Excludes via exclusion patterns
   - Excludes without required_context (revenue synonyms)
   - Excludes false positives (years, dates)
   - Passes valid matches through filters

4. **Confidence Scoring** (2-3 tests)
   - Base confidence 0.5
   - Bonus for specific patterns
   - Bonus for table source

5. **Integration** (2 tests)
   - Full stage execution with mock context
   - Empty input returns success with zero candidates

### Known Edge Cases to Test

- Keyword spanning `[CELL]` markers (should match)
- Multiple metrics in same segment
- Nested tables (multiple tables in context)
- Empty segments list

## Acceptance Criteria

- [ ] `MetricCandidate` dataclass defined with required fields
- [ ] `CandidateGenerationStage` class with `process()` method following stage protocol
- [ ] Imports and uses `get_metric_keywords()` from V1 keyword_config
- [ ] Imports and uses `get_exclusion_patterns()` from V1 keyword_config
- [ ] Imports and uses `get_required_context()` from V1 keyword_config
- [ ] Imports and uses `FalsePositiveFilter` from V1 false_positive_filter
- [ ] Scans segment text for keyword matches
- [ ] Scans table cells (text + header_path + stub_path)
- [ ] Applies exclusion patterns per metric
- [ ] Applies required_context filters
- [ ] Applies false positive filtering
- [ ] Creates MetricCandidate with valid SourceLocator
- [ ] Stub in `pipeline.py` replaced with real import
- [ ] `stages/__init__.py` exports CandidateGenerationStage
- [ ] **15+ unit tests** covering scanning, filtering, confidence
- [ ] **Test coverage ≥90%** for candidate_generation.py
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] `mypy src/extraction_v2/stages/candidate_generation.py --strict` passes

## Do NOT

- Modify `config/metric_keywords.yaml` (use as-is)
- Modify V1 modules (`keyword_config.py`, `false_positive_filter.py`)
- Add LLM calls - this stage is rule-based only
- Change existing stage implementations (ingestion, section_classification, table_reconstruction)
- Add database persistence (that's Phase 12)

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_candidate_generation.py -v

# Check coverage (must be ≥90%)
pytest tests/unit/extraction_v2/test_candidate_generation.py \
  --cov=src/extraction_v2/stages/candidate_generation --cov-report=term-missing

# Type safety check
mypy src/extraction_v2/stages/candidate_generation.py --strict

# Lint
ruff check src/extraction_v2/stages/candidate_generation.py

# Verify pipeline still works
pytest tests/unit/extraction_v2/ -v -q

# Full regression test
pytest tests/unit/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task V2-PHASE-6: Candidate Generation Stage
# Run: bash verify_v2_phase_6.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task V2-PHASE-6: Candidate Generation Stage"
echo "═══════════════════════════════════════════════════════════════"

# Criterion 1: File exists
echo "✓ Checking: candidate_generation.py exists..."
test -f src/extraction_v2/stages/candidate_generation.py

# Criterion 2: Test file exists
echo "✓ Checking: test file exists..."
test -f tests/unit/extraction_v2/test_candidate_generation.py

# Criterion 3: Stage exports
echo "✓ Checking: CandidateGenerationStage exported..."
python3 -c "from src.extraction_v2.stages import CandidateGenerationStage"

# Criterion 4: Pipeline imports work
echo "✓ Checking: Pipeline imports CandidateGenerationStage..."
python3 -c "from src.extraction_v2.pipeline import V2Pipeline; p = V2Pipeline()"

# Criterion 5: Test coverage >= 90%
echo "✓ Checking: Test coverage ≥ 90%..."
pytest tests/unit/extraction_v2/test_candidate_generation.py \
  --cov=src/extraction_v2/stages/candidate_generation \
  --cov-report=term --cov-fail-under=90 -q

# Criterion 6: Type safety
echo "✓ Checking: mypy passes..."
mypy src/extraction_v2/stages/candidate_generation.py --strict

# Criterion 7: Lint passes
echo "✓ Checking: ruff passes..."
ruff check src/extraction_v2/stages/candidate_generation.py

# Criterion 8: Full V2 test suite
echo "✓ Running V2 extraction tests..."
pytest tests/unit/extraction_v2/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task V2-PHASE-6!"
echo "═══════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size.**

| Task Size | Evaluation Depth |
|-----------|------------------|
| M | Thorough: full checklist, comprehensive improvement search |

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
class MetricCandidate:
    """Candidate metric mention found in content."""
    candidate_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metric_id: str = ""
    match_text: str = ""
    source_locator: SourceLocator = field(default_factory=SourceLocator)
    source_type: SourceType = SourceType.TEXT
    confidence: float = 0.5
    context_text: str = ""


class CandidateGenerationStage:
    """Stage 6: Metric Candidate Generation."""

    def __init__(self) -> None:
        self._keywords = get_metric_keywords()
        self._exclusions = get_exclusion_patterns()
        self._required_context = get_required_context()
        self._fp_filter = FalsePositiveFilter()
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        self._compile_patterns()

    def process(self, context: PipelineContext) -> StageResult:
        # 1. Scan segments
        # 2. Scan tables
        # 3. Filter and score
        # 4. Return StageResult
        pass
```
</details>

## Reference

- **Issue source**: V2_IMPLEMENTATION_ROADMAP.md Phase 6
- **Dependencies**: V2-PHASE-1 (ingestion), V2-PHASE-3 (tables)
- **Related**: V1 candidate_generator.py (reference for patterns)

---

**Last Updated**: 2026-02-03
**Format Version**: 2.6

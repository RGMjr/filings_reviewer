# WORKER PROMPT: Task V2-PHASE-10 - Deduplication Stage

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-10
TASK NAME:     Implement Deduplication Stage for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        V2_IMPLEMENTATION_ROADMAP.md - Phase 10
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-60 minutes
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Pure transformation stage, no external dependencies
TASK SIZE:     S
DEPENDS ON:    V2-PHASE-9 (Fact Construction)
UNLOCKS:       V2-PHASE-11 (Validation)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create the Deduplication Stage (Stage 10) for the V2 extraction pipeline. This stage identifies duplicate `MetricFact` objects (same metric, period, value within tolerance), selects a primary based on source quality, and links alternates via the `alternate_evidence` field.

**Business Rationale**: A single metric value may be mentioned multiple times in a filing (e.g., in a table and again in narrative text). We need to merge duplicates to avoid double-counting while preserving all source evidence for human reviewers.

**Current Behavior**: `DeduplicationStage` stub in `pipeline.py` returns empty results.

**Desired Behavior**: Stage groups facts by identity tuple, selects highest-quality source as primary, and links alternate fact_ids to preserve all evidence.

## Prerequisites

- V2-PHASE-9 (Fact Construction): Provides `context.facts` with complete MetricFact objects
- Understanding of `MetricFact.identity_tuple()` and `is_duplicate_of()` methods in `models.py`

## Files to Create

1. **`src/extraction_v2/stages/deduplication.py`** - DeduplicationStage implementation (~100-150 lines)
2. **`tests/unit/extraction_v2/test_deduplication.py`** - Unit tests (~150-200 lines)

## Files to Modify

1. **`src/extraction_v2/stages/__init__.py`** - Export DeduplicationStage

## Files to Read (Context Only)

- `src/extraction_v2/models.py` - MetricFact (identity_tuple, is_duplicate_of, alternate_evidence)
- `src/extraction_v2/stages/fact_construction.py` - Stage implementation pattern
- `src/extraction_v2/pipeline.py` - PipelineContext, StageResult structures

## Implementation Requirements

### Core Functionality

1. **DeduplicationStage Class**
   - `__init__()` with optional `value_tolerance` parameter (default 0.02 = 2%)
   - `process(context: PipelineContext) -> StageResult` following stage protocol

2. **Grouping by Identity**
   - Group facts by identity tuple: `(metric_id, period_start, period_end, unit, value±tolerance, scope, cohort_def, customer_type)`
   - Use `MetricFact.is_duplicate_of()` method for comparison (handles value tolerance)
   - Facts with identical tuples (within tolerance) are duplicates

3. **Primary Selection by Source Quality**
   Source priority ranking (highest to lowest quality):
   - `SourceType.HTML_TABLE` → highest quality (structured, parseable)
   - `SourceType.TEXT` → second (explicit narrative)
   - `SourceType.OCR_TABLE` → third (OCR may have errors)
   - `SourceType.CHART` → lowest (chart values less reliable)

   Within same source type, prefer higher confidence score.

4. **Alternate Evidence Linking**
   For each duplicate group:
   - Select primary fact based on source quality
   - Add fact_ids of all alternates to primary's `alternate_evidence` list
   - Return only primary facts (alternates are discarded from facts list but preserved via fact_id links)

5. **Output**
   - Populate `context.deduplicated_facts` with primary facts only
   - Keep `context.facts` unchanged (for audit trail)
   - Return StageResult with deduplication statistics

### Error Handling

- **Empty facts list**: Return success with zero output
- **Facts with None values**: Use `is_duplicate_of()` which handles None comparison
- **Individual grouping errors**: Log warning and treat as unique fact

### Performance Requirements

- Process 500 facts in <500ms
- O(n²) comparison acceptable for typical batch sizes (<1000 facts per filing)

## Test Requirements

### Coverage Target: **≥80%** for `deduplication.py`

### Test Categories (12+ tests recommended)

1. **Grouping Logic** (3-4 tests)
   - Two identical facts → grouped together
   - Facts with different metric_id → separate groups
   - Facts with values within 2% tolerance → grouped
   - Facts with values outside tolerance → separate

2. **Primary Selection** (4-5 tests)
   - HTML_TABLE beats TEXT source
   - TEXT beats OCR_TABLE source
   - OCR_TABLE beats CHART source
   - Same source type → higher confidence wins

3. **Alternate Evidence Linking** (2-3 tests)
   - Primary fact has alternate fact_ids
   - Alternates not in output list
   - Single fact (no duplicates) → no alternates

4. **Edge Cases** (2-3 tests)
   - Empty facts list → empty output
   - All unique facts → all preserved
   - Three-way duplicate → one primary, two alternates

### Known Edge Cases to Test

- Facts with `value=None` (text-only facts)
- Facts with `period_start=None` (unknown period)
- Facts with identical values but different units → separate
- Facts with same everything except cohort_def → separate

## Acceptance Criteria

- [ ] AC-1: `src/extraction_v2/stages/deduplication.py` exists
- [ ] AC-2: `DeduplicationStage.process()` groups facts by identity tuple
- [ ] AC-3: Primary selection follows source quality ranking
- [ ] AC-4: Alternate fact_ids linked in primary's `alternate_evidence`
- [ ] AC-5: Only primary facts in `context.deduplicated_facts`
- [ ] AC-6: Pipeline integration: stage exported in `__init__.py`
- [ ] AC-7: Tests in `tests/unit/extraction_v2/test_deduplication.py`
- [ ] AC-8: Coverage ≥80% for new module
- [ ] AC-9: `mypy --strict` passes on new module
- [ ] AC-10: `ruff check` passes

## Do NOT

- Modify `config/metric_keywords.yaml` (not relevant to this stage)
- Modify V1 modules
- Add LLM calls - this stage is rule-based only
- Change MetricFact model (use existing identity_tuple and is_duplicate_of methods)
- Add database persistence (that's Phase 12)
- Modify existing stage implementations

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_deduplication.py -v

# Check coverage (must be ≥80%)
pytest tests/unit/extraction_v2/test_deduplication.py \
  --cov=src/extraction_v2/stages/deduplication --cov-report=term-missing

# Type safety check
mypy src/extraction_v2/stages/deduplication.py --strict

# Lint
ruff check src/extraction_v2/stages/deduplication.py

# Verify pipeline still works
pytest tests/unit/extraction_v2/ -v -q

# Full regression test
pytest tests/unit/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task V2-PHASE-10: Deduplication Stage
# Run: bash verify_v2_phase_10.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task V2-PHASE-10: Deduplication Stage"
echo "═══════════════════════════════════════════════════════════════"

# AC-1: File exists
echo "✓ Checking: deduplication.py exists..."
test -f src/extraction_v2/stages/deduplication.py

# AC-6: Stage exports
echo "✓ Checking: DeduplicationStage exported..."
python3 -c "from src.extraction_v2.stages import DeduplicationStage"

# AC-7: Test file exists
echo "✓ Checking: test file exists..."
test -f tests/unit/extraction_v2/test_deduplication.py

# AC-8: Test coverage >= 80%
echo "✓ Checking: Test coverage ≥ 80%..."
pytest tests/unit/extraction_v2/test_deduplication.py \
  --cov=src/extraction_v2/stages/deduplication \
  --cov-report=term --cov-fail-under=80 -q

# AC-9: Type safety
echo "✓ Checking: mypy passes..."
mypy src/extraction_v2/stages/deduplication.py --strict

# AC-10: Lint passes
echo "✓ Checking: ruff passes..."
ruff check src/extraction_v2/stages/deduplication.py

# Full V2 test suite
echo "✓ Running V2 extraction tests..."
pytest tests/unit/extraction_v2/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task V2-PHASE-10!"
echo "═══════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size.**

| Task Size | Evaluation Depth |
|-----------|------------------|
| S | Standard: review checklist, identify 1-2 improvements max |

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
"""V2 Deduplication Stage."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricFact, SourceType

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)

# Source quality ranking (higher = better)
SOURCE_QUALITY_RANK: dict[SourceType, int] = {
    SourceType.HTML_TABLE: 4,
    SourceType.TEXT: 3,
    SourceType.OCR_TABLE: 2,
    SourceType.CHART: 1,
}


class DeduplicationStage:
    """Stage 10: Deduplication."""

    def __init__(self, value_tolerance: float = 0.02) -> None:
        self.value_tolerance = value_tolerance

    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()

        # Group duplicates
        groups = self._group_duplicates(context.facts)

        # Select primaries and link alternates
        primaries: list[MetricFact] = []
        for group in groups:
            primary = self._select_primary(group)
            if len(group) > 1:
                # Link alternates
                primary.alternate_evidence = [
                    f.fact_id for f in group if f.fact_id != primary.fact_id
                ]
            primaries.append(primary)

        context.deduplicated_facts = primaries

        # Build result
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        return StageResult(
            stage=PipelineStage.DEDUPLICATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(context.facts),
            items_output=len(primaries),
            metadata={
                "duplicates_merged": len(context.facts) - len(primaries),
                "groups_with_alternates": sum(1 for g in groups if len(g) > 1),
            },
        )

    def _group_duplicates(self, facts: list[MetricFact]) -> list[list[MetricFact]]:
        """Group facts that are duplicates of each other."""
        if not facts:
            return []

        groups: list[list[MetricFact]] = []
        used: set[str] = set()

        for i, fact in enumerate(facts):
            if fact.fact_id in used:
                continue

            group = [fact]
            used.add(fact.fact_id)

            for other in facts[i + 1:]:
                if other.fact_id in used:
                    continue
                if fact.is_duplicate_of(other, self.value_tolerance):
                    group.append(other)
                    used.add(other.fact_id)

            groups.append(group)

        return groups

    def _select_primary(self, group: list[MetricFact]) -> MetricFact:
        """Select the highest-quality fact as primary."""
        if len(group) == 1:
            return group[0]

        # Sort by source quality (desc), then confidence (desc)
        return max(
            group,
            key=lambda f: (
                SOURCE_QUALITY_RANK.get(f.source_type, 0),
                f.confidence,
            ),
        )
```
</details>

## Reference

- **Issue source**: V2_IMPLEMENTATION_ROADMAP.md Phase 10
- **Dependencies**: V2-PHASE-9 (Fact Construction)
- **Related**: models.py (MetricFact.identity_tuple, is_duplicate_of)

---

**Last Updated**: 2026-02-04
**Format Version**: 2.6

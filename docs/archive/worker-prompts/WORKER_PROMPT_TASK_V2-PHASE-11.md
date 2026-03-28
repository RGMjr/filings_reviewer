# WORKER PROMPT: Task V2-PHASE-11 - Validation & Review Routing Stage

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       V2-PHASE-11
TASK NAME:     Implement Validation & Review Routing Stage for V2 Extraction Pipeline
WORKSTREAM:    V2 Extraction Pipeline
SOURCE:        V2_IMPLEMENTATION_ROADMAP.md - Phase 11
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-60 minutes
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Pure transformation stage, no external dependencies
TASK SIZE:     S
DEPENDS ON:    V2-PHASE-10 (Deduplication)
UNLOCKS:       V2-PHASE-12 (Database Persistence)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════

## Objective

Create the Validation & Review Routing Stage (Stage 11) for the V2 extraction pipeline. This stage validates fact schema completeness, routes facts to human review or auto-acceptance based on confidence thresholds, and sets appropriate review reasons.

**Business Rationale**: Not all extracted facts are equal quality. High-confidence facts can be auto-accepted while low-confidence facts need human review. Very low-confidence facts should be flagged as auto-reject candidates. This routing saves reviewer time by focusing attention on borderline cases.

**Current Behavior**: `ValidationStage` stub exists in `pipeline.py` (lines 435-477) with basic confidence routing. It operates on `context.facts` but should use `context.deduplicated_facts` after Phase 10.

**Desired Behavior**: Stage validates schema completeness, routes facts by confidence with detailed review reasons, and is extracted into a standalone module following the established stage pattern.

## Prerequisites

- V2-PHASE-10 (Deduplication): Provides `context.deduplicated_facts` with primary facts only
- Understanding of `MetricFact` and `ReviewStatus` in `models.py`
- Understanding of confidence thresholds in `PipelineConfig`

## Files to Create

1. **`src/extraction_v2/stages/validation.py`** - ValidationStage implementation (~150-200 lines)
2. **`tests/unit/extraction_v2/test_validation.py`** - Unit tests (~200-250 lines)

## Files to Modify

1. **`src/extraction_v2/stages/__init__.py`** - Export ValidationStage
2. **`src/extraction_v2/pipeline.py`** - Import ValidationStage from stages module, remove inline stub

## Files to Read (Context Only)

- `src/extraction_v2/models.py` - MetricFact, ReviewStatus, Unit, PeriodType
- `src/extraction_v2/stages/deduplication.py` - Stage implementation pattern
- `src/extraction_v2/pipeline.py` - PipelineConfig thresholds, existing ValidationStage stub

## Implementation Requirements

### Core Functionality

1. **ValidationStage Class**
   - `__init__()` with optional threshold overrides (auto_accept, auto_reject)
   - `process(context: PipelineContext) -> StageResult` following stage protocol

2. **Schema Validation**
   Validate required fields are populated for each fact:
   - `canonical_metric_id` (required, non-empty)
   - `value` OR `value_raw` (at least one required)
   - `source_locator.segment_id` or `source_locator.table_id` or `source_locator.img_id` (at least one)
   - `evidence_pack.snippet_html` (non-empty)

   Schema validation failures should set `requires_review=True` with appropriate `review_reason`.

3. **Confidence-Based Routing**
   Use thresholds from `context.config`:
   - `confidence >= min_confidence_auto_accept (0.90)`: Auto-accept
     - Set `requires_review = False`
     - Set `review_status = ReviewStatus.AUTO_ACCEPTED`
     - Clear `review_reason`
   - `confidence < max_confidence_auto_reject (0.15)`: Auto-reject candidate
     - Set `requires_review = True`
     - Set `review_status = ReviewStatus.PENDING_REVIEW`
     - Set `review_reason = "Low confidence (auto-reject candidate)"`
   - Otherwise: Pending review
     - Set `requires_review = True`
     - Set `review_status = ReviewStatus.PENDING_REVIEW`
     - Set `review_reason` based on why (see Detailed Review Reasons)

4. **Detailed Review Reasons**
   Facts should have specific review reasons when applicable:
   - Schema validation failures: "Missing required field: {field_name}"
   - OCR source: "OCR-based extraction requires verification"
   - Chart source: "Chart-based extraction requires verification"
   - Ambiguous period: "Period could not be determined with confidence"
   - Low confidence: "Confidence {score:.0%} below auto-accept threshold"

   If multiple reasons apply, concatenate with "; "

5. **Output**
   - Update facts in-place within `context.deduplicated_facts`
   - Also update `context.facts` to maintain consistency (pending_review counts, etc.)
   - Return StageResult with routing statistics

### Error Handling

- **Empty facts list**: Return success with zero output
- **Missing config thresholds**: Use defaults (0.90 auto-accept, 0.15 auto-reject)
- **Schema validation errors**: Log warning, flag for review, continue processing

### StageResult Metadata

Return these statistics in metadata:
- `auto_accepted`: Count of facts auto-accepted
- `pending_review`: Count of facts flagged for review
- `auto_reject_candidates`: Count of very low confidence facts
- `schema_validation_failures`: Count of facts with missing required fields

## Test Requirements

### Coverage Target: **≥80%** for `validation.py`

### Test Categories (15+ tests recommended)

1. **Confidence Routing** (5-6 tests)
   - Confidence >= 0.90 → auto-accepted, requires_review=False
   - Confidence 0.89 → pending review
   - Confidence 0.15 → pending review (boundary)
   - Confidence 0.14 → auto-reject candidate
   - Confidence 0.0 → auto-reject candidate
   - Multiple facts with mixed confidence levels

2. **Schema Validation** (4-5 tests)
   - Missing canonical_metric_id → flagged for review
   - Missing both value and value_raw → flagged for review
   - Missing source locator (no segment/table/img id) → flagged for review
   - Missing snippet_html → flagged for review
   - Valid fact passes schema validation

3. **Review Reason Assignment** (3-4 tests)
   - OCR source adds verification reason
   - Chart source adds verification reason
   - Multiple reasons concatenated
   - High confidence fact has no review reason

4. **Edge Cases** (3-4 tests)
   - Empty facts list → empty output, success
   - All facts auto-accepted → zero pending review
   - All facts low confidence → all flagged
   - Custom thresholds via config override

### Known Edge Cases to Test

- Fact with `value=None` but `value_raw` populated → valid
- Fact with confidence exactly at threshold boundaries
- Fact already having a `review_reason` from prior stage → preserve or append

## Acceptance Criteria

- [ ] AC-1: `src/extraction_v2/stages/validation.py` exists
- [ ] AC-2: `ValidationStage.process()` routes facts by confidence thresholds
- [ ] AC-3: Schema validation checks required fields
- [ ] AC-4: `review_reason` populated with specific details for flagged facts
- [ ] AC-5: `review_status` enum correctly set (AUTO_ACCEPTED vs PENDING_REVIEW)
- [ ] AC-6: Pipeline integration: stage exported in `__init__.py`
- [ ] AC-7: Pipeline integration: `ValidationStage` imported from stages module in pipeline.py
- [ ] AC-8: Tests in `tests/unit/extraction_v2/test_validation.py`
- [ ] AC-9: Coverage ≥80% for new module
- [ ] AC-10: `mypy --strict` passes on new module
- [ ] AC-11: `ruff check` passes

## Do NOT

- Modify `config/metric_keywords.yaml` (not relevant to this stage)
- Modify V1 modules
- Add LLM calls - this stage is rule-based only
- Change MetricFact model fields (use existing fields)
- Add database persistence (that's Phase 12)
- Modify existing stage implementations (except removing stub from pipeline.py)

## Verification Commands

```bash
# Run new tests
pytest tests/unit/extraction_v2/test_validation.py -v

# Check coverage (must be ≥80%)
pytest tests/unit/extraction_v2/test_validation.py \
  --cov=src/extraction_v2/stages/validation --cov-report=term-missing

# Type safety check
mypy src/extraction_v2/stages/validation.py --strict

# Lint
ruff check src/extraction_v2/stages/validation.py

# Verify pipeline still works
pytest tests/unit/extraction_v2/ -v -q

# Full regression test
pytest tests/unit/ --no-cov -q
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Auto-generated verification for Task V2-PHASE-11: Validation Stage
# Run: bash verify_v2_phase_11.sh

set -e  # Exit on any error
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task V2-PHASE-11: Validation & Review Routing Stage"
echo "═══════════════════════════════════════════════════════════════"

# AC-1: File exists
echo "✓ Checking: validation.py exists..."
test -f src/extraction_v2/stages/validation.py

# AC-6: Stage exports
echo "✓ Checking: ValidationStage exported from stages..."
python3 -c "from src.extraction_v2.stages import ValidationStage"

# AC-7: Pipeline imports from stages
echo "✓ Checking: ValidationStage imported in pipeline..."
python3 -c "from src.extraction_v2.stages.validation import ValidationStage"

# AC-8: Test file exists
echo "✓ Checking: test file exists..."
test -f tests/unit/extraction_v2/test_validation.py

# AC-9: Test coverage >= 80%
echo "✓ Checking: Test coverage ≥ 80%..."
pytest tests/unit/extraction_v2/test_validation.py \
  --cov=src/extraction_v2/stages/validation \
  --cov-report=term --cov-fail-under=80 -q

# AC-10: Type safety
echo "✓ Checking: mypy passes..."
mypy src/extraction_v2/stages/validation.py --strict

# AC-11: Lint passes
echo "✓ Checking: ruff passes..."
ruff check src/extraction_v2/stages/validation.py

# Full V2 test suite
echo "✓ Running V2 extraction tests..."
pytest tests/unit/extraction_v2/ --no-cov -q

echo "═══════════════════════════════════════════════════════════════"
echo "✅ All acceptance criteria verified for Task V2-PHASE-11!"
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
"""V2 Validation & Review Routing Stage."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricFact, ReviewStatus, SourceType

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ValidationStage:
    """Stage 11: Validation & Review Routing."""

    def __init__(
        self,
        auto_accept_threshold: float = 0.90,
        auto_reject_threshold: float = 0.15,
    ) -> None:
        self.auto_accept_threshold = auto_accept_threshold
        self.auto_reject_threshold = auto_reject_threshold

    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()

        # Use deduplicated facts if available, otherwise facts
        facts = context.deduplicated_facts or context.facts

        # Get thresholds from config
        auto_accept = getattr(
            context.config, "min_confidence_auto_accept", self.auto_accept_threshold
        )
        auto_reject = getattr(
            context.config, "max_confidence_auto_reject", self.auto_reject_threshold
        )

        stats = {
            "auto_accepted": 0,
            "pending_review": 0,
            "auto_reject_candidates": 0,
            "schema_validation_failures": 0,
        }

        for fact in facts:
            # Validate schema
            schema_issues = self._validate_schema(fact)
            if schema_issues:
                stats["schema_validation_failures"] += 1

            # Build review reasons
            reasons = []
            if schema_issues:
                reasons.extend(schema_issues)

            # Source-based reasons
            if fact.source_type == SourceType.OCR_TABLE:
                reasons.append("OCR-based extraction requires verification")
            elif fact.source_type == SourceType.CHART:
                reasons.append("Chart-based extraction requires verification")

            # Route by confidence
            if fact.confidence >= auto_accept and not reasons:
                fact.requires_review = False
                fact.review_status = ReviewStatus.AUTO_ACCEPTED
                fact.review_reason = None
                stats["auto_accepted"] += 1
            elif fact.confidence < auto_reject:
                fact.requires_review = True
                fact.review_status = ReviewStatus.PENDING_REVIEW
                reasons.append("Low confidence (auto-reject candidate)")
                fact.review_reason = "; ".join(reasons)
                stats["auto_reject_candidates"] += 1
                stats["pending_review"] += 1
            else:
                fact.requires_review = True
                fact.review_status = ReviewStatus.PENDING_REVIEW
                if not reasons:
                    reasons.append(
                        f"Confidence {fact.confidence:.0%} below auto-accept threshold"
                    )
                fact.review_reason = "; ".join(reasons)
                stats["pending_review"] += 1

        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        return StageResult(
            stage=PipelineStage.VALIDATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(facts),
            items_output=len(facts),
            metadata=stats,
        )

    def _validate_schema(self, fact: MetricFact) -> list[str]:
        """Validate required schema fields."""
        issues: list[str] = []

        if not fact.canonical_metric_id:
            issues.append("Missing required field: canonical_metric_id")

        if fact.value is None and not fact.value_raw:
            issues.append("Missing required field: value or value_raw")

        loc = fact.source_locator
        if not (loc.segment_id or loc.table_id or loc.img_id):
            issues.append("Missing required field: source_locator (no segment/table/img id)")

        if not fact.evidence_pack.snippet_html:
            issues.append("Missing required field: evidence_pack.snippet_html")

        return issues
```
</details>

## Reference

- **Issue source**: V2_IMPLEMENTATION_ROADMAP.md Phase 11
- **Dependencies**: V2-PHASE-10 (Deduplication)
- **Related**: models.py (MetricFact, ReviewStatus), pipeline.py (PipelineConfig thresholds)

---

**Last Updated**: 2026-02-04
**Format Version**: 2.6

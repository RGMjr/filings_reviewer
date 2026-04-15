# Worker Prompt: Refactor _process_segment (CC=57)

## Task ID: REV-07
## Priority: P2 (Maintainability)
## Effort: L (4-8 hours)
## Finding IDs: C-D3-001, G-D3-001, C-D3-001 (Gemini)

---

## Problem Statement

`CandidateGenerator._process_segment` has **cyclomatic complexity of 57**, making it extremely difficult to test, debug, and modify. The function handles 7 distinct phases in a single 400+ line monolithic function.

### Current State

- **400+ lines** of mixed responsibilities
- **57 independent execution paths**
- **7 phases** interleaved with exception handling
- **Stateful caching** mixed with logic
- **All 3 models** flagged this as critical

---

## Files to Modify

- `src/review/candidate_generator.py` - Refactor main function
- `src/review/models.py` (possibly) - Add supporting types
- `tests/unit/review/test_candidate_generator.py` - Update tests

---

## Acceptance Criteria

1. [ ] _process_segment becomes orchestrator only (< 50 LOC)
2. [ ] Each phase extracted to separate method (< 80 LOC each)
3. [ ] SegmentProcessingContext dataclass for shared state
4. [ ] SegmentStats as proper dataclass (not dict)
5. [ ] Each phase independently testable
6. [ ] All existing tests pass
7. [ ] Cyclomatic complexity < 15 for main function

---

## Current Structure Analysis

```python
def _process_segment(self, filing_id, company_id, segment, db=None):
    # Phase 1: Validation & Setup (~30 lines)
    # Phase 2: Pre-computation (keywords, words, boundaries) (~50 lines)
    # Phase 3: Number iteration with exception handling (~100 lines)
    # Phase 4: Keyword matching per number (~80 lines)
    # Phase 5: Feature computation & scoring (~60 lines)
    # Phase 6: Candidate construction (~40 lines)
    # Phase 7: Post-filters (learned rules, type validation) (~50 lines)
    return candidates, segment_stats
```

---

## Target Structure

### Step 1: Create Supporting Types

```python
# src/review/models.py (or candidate_generator.py)
from dataclasses import dataclass, field
from typing import Optional, Sequence, Any

@dataclass(frozen=True)
class SegmentProcessingContext:
    """Immutable context passed through processing pipeline."""
    filing_id: int
    company_id: int
    segment: dict
    text: str
    source_segment_id: Optional[int]
    numbers: Sequence["NumberMatch"]
    all_keywords: Sequence["KeywordMatch"]
    boundaries: Optional[list] = None
    sentence_boundaries: Optional[list] = None
    table_row_parser: Optional[Any] = None
    cached_words: list = field(default_factory=list)


@dataclass
class SegmentStats:
    """Statistics from segment processing."""
    numbers_found: int = 0
    numbers_failed: int = 0
    false_positives_filtered: int = 0
    filtered_by_learned_rules: int = 0
    excluded_by_number_context: int = 0
    filtered_by_type_validation: int = 0
    candidates_generated: int = 0

    def inc(self, field_name: str, n: int = 1) -> None:
        """Increment a counter field."""
        current = getattr(self, field_name)
        setattr(self, field_name, current + n)
```

### Step 2: Refactor Main Function

```python
def _process_segment(
    self,
    filing_id: int,
    company_id: int,
    segment: SegmentDict,
    db: Any | None = None,
) -> tuple[list[ReviewCandidate], SegmentStats]:
    """
    Process a single segment to generate review candidates.

    Orchestrates pipeline phases:
    1. Prepare context
    2. Process numbers
    3. Post-process candidates
    """
    # Phase 1: Prepare context (returns None if segment should be skipped)
    ctx = self._prepare_segment_context(filing_id, company_id, segment)
    if ctx is None:
        return [], SegmentStats()

    # Phase 2: Process all numbers in segment
    candidates, stats = self._process_numbers(ctx)

    # Phase 3: Apply post-processing filters
    candidates = self._post_process_candidates(candidates, ctx, db, stats)

    stats.candidates_generated = len(candidates)
    return candidates, stats
```

### Step 3: Extract Phase Methods

```python
def _prepare_segment_context(
    self,
    filing_id: int,
    company_id: int,
    segment: SegmentDict,
) -> Optional[SegmentProcessingContext]:
    """
    Validate segment and prepare processing context.

    Returns None if segment should be skipped (e.g., definition-only).
    """
    text = segment.get("raw_text", "")
    if not text or len(text) < self.config.min_segment_length:
        return None

    segment_type = segment.get("segment_type", "text")

    # Skip definition-only segments if configured
    if segment_type == "definition" and self.config.skip_definition_segments:
        return None

    # Pre-compute numbers
    numbers = self._extract_numbers(text, segment_type)
    if not numbers:
        return None

    # Pre-compute keywords
    all_keywords = self.keyword_matcher.find_all_keywords(text, segment_type)

    # Pre-compute boundaries if enabled
    boundaries = None
    sentence_boundaries = None
    if self.config.enable_boundary_detection:
        boundaries = self._boundary_detector.find_boundaries(text)
    if self.config.detect_sentences:
        sentence_boundaries = self._boundary_detector.find_sentence_boundaries(
            text, segment_type
        )

    # Pre-compute table row parser if applicable
    table_row_parser = None
    if segment_type == "table":
        table_row_parser = TableRowParser(text)

    # Pre-compute word positions for distance calculations
    cached_words = self._cache_word_positions(text)

    return SegmentProcessingContext(
        filing_id=filing_id,
        company_id=company_id,
        segment=segment,
        text=text,
        source_segment_id=segment.get("source_segment_id"),
        numbers=numbers,
        all_keywords=all_keywords,
        boundaries=boundaries,
        sentence_boundaries=sentence_boundaries,
        table_row_parser=table_row_parser,
        cached_words=cached_words,
    )


def _process_numbers(
    self,
    ctx: SegmentProcessingContext,
) -> tuple[list[ReviewCandidate], SegmentStats]:
    """
    Process each number in context to generate candidates.
    """
    candidates: list[ReviewCandidate] = []
    stats = SegmentStats(numbers_found=len(ctx.numbers))
    seen: set[tuple[int, str]] = set()

    for number in ctx.numbers:
        try:
            number_candidates = self._process_one_number(ctx, number, seen, stats)
            candidates.extend(number_candidates)
        except NumberProcessingError as e:
            stats.inc("numbers_failed")
            logger.warning(f"Number processing error: {e}")
        except Exception as e:
            stats.inc("numbers_failed")
            logger.exception(f"Unexpected error processing number: {e}")
            if self.config.raise_on_unexpected:
                raise

    return candidates, stats


def _process_one_number(
    self,
    ctx: SegmentProcessingContext,
    number: NumberMatch,
    seen: set[tuple[int, str]],
    stats: SegmentStats,
) -> list[ReviewCandidate]:
    """
    Process a single number to generate candidates.

    Phases:
    1. False positive filtering
    2. Keyword matching
    3. Feature computation
    4. Candidate construction
    """
    candidates: list[ReviewCandidate] = []

    # Phase 1: Early false positive filtering
    is_fp, fp_reason = self.fp_filter.is_false_positive(
        ctx.text, number.value, number.position
    )
    if is_fp:
        stats.inc("false_positives_filtered")
        return []

    # Phase 2: Find keywords near this number
    nearby_keywords = self.keyword_matcher.find_keywords_near_number(
        number,
        ctx.all_keywords,
        boundaries=ctx.boundaries,
        sentence_boundaries=ctx.sentence_boundaries,
        text=ctx.text,
        segment_type=ctx.segment.get("segment_type"),
        table_row_parser=ctx.table_row_parser,
    )

    if not nearby_keywords:
        return []

    # Phase 3: Check number-context exclusions
    if self.keyword_matcher.should_exclude_for_number_context(
        ctx.text, number.position, ctx.table_row_parser
    ):
        stats.inc("excluded_by_number_context")
        return []

    # Phase 4: Generate candidate for each keyword match
    for keyword in nearby_keywords:
        candidate = self._create_candidate(ctx, number, keyword, seen, stats)
        if candidate:
            candidates.append(candidate)

    return candidates


def _post_process_candidates(
    self,
    candidates: list[ReviewCandidate],
    ctx: SegmentProcessingContext,
    db: Any | None,
    stats: SegmentStats,
) -> list[ReviewCandidate]:
    """
    Apply post-processing filters to candidates.
    """
    # Filter by learned rules
    if db and self.config.apply_learned_rules:
        applicator = self._get_rule_applicator(db)
        if applicator:
            before_count = len(candidates)
            candidates = [c for c in candidates if not applicator.should_filter(c)[0]]
            stats.inc("filtered_by_learned_rules", before_count - len(candidates))

    # Filter by type validation
    if self.config.enable_type_validation:
        before_count = len(candidates)
        candidates = [c for c in candidates if self._validate_candidate_type(c)]
        stats.inc("filtered_by_type_validation", before_count - len(candidates))

    return candidates
```

---

## Verification Commands

```bash
# Run existing tests (must all pass)
pytest tests/unit/review/test_candidate_generator.py -v

# Check cyclomatic complexity of refactored function
radon cc src/review/candidate_generator.py -a -s --show-complexity | grep _process_segment
# Target: CC < 15

# Run gold standard (extraction logic unchanged)
pytest -m gold_standard --gold-standard-mode=fresh -v

# Full test suite
pytest tests/ -v --tb=short
```

---

## Risk Mitigation

1. **Preserve exact behavior**: This is a PURE REFACTOR - no logic changes
2. **Run tests after each extraction**: Don't extract all phases at once
3. **Use git commits per phase**: Easy rollback if issues arise
4. **Verify with gold standard**: Ensure extraction accuracy unchanged

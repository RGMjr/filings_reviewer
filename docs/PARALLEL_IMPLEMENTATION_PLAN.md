# Parallel Implementation Plan: Option 1 (2 Workstreams)

**Date**: 2025-12-11
**Duration**: 4 days (with 2 parallel workstreams)
**Total Effort**: 11-16 hours

---

## Overview

Two independent workstreams running in parallel:

- **Workstream A**: Test Infrastructure (P2 + P3) - 5-7 hours
- **Workstream B**: Source Code Quality (P1 → P4 → P5) - 5-7 hours

Both can start immediately. Workstream A has zero dependencies on Workstream B.

---

## Workstream A: Test Infrastructure (P2 + P3)

**Owner**: Developer A or Solo (can pause/resume anytime)
**Duration**: 5-7 hours
**Branch**: `feature/test-infrastructure-improvements`
**Dependencies**: None - can start immediately

### Task A1: Performance Benchmarking (P2) - 3-4 hours

#### A1.1: Setup Performance Test Infrastructure (30 min)

**Files to create:**
- `tests/performance/__init__.py`
- `tests/performance/conftest.py`
- `tests/performance/test_candidate_generation_benchmark.py`

**Tasks:**
1. Create `tests/performance/` directory
2. Add pytest markers to `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   markers = [
       "benchmark: Performance benchmark tests (deselect with '-m \"not benchmark\"')",
   ]
   ```
3. Create conftest.py with benchmark fixtures:
   - `benchmark_db` - Clean database for benchmarks
   - `realistic_segments` - Generate 100/500/1000 segment samples
   - `large_filing_data` - Realistic filing with 500+ segments

**Validation:**
```bash
pytest tests/performance/ -v -m benchmark
```

---

#### A1.2: Implement Throughput Benchmark (1 hour)

**File**: `tests/performance/test_candidate_generation_benchmark.py`

**Tests to implement:**

```python
@pytest.mark.benchmark
def test_throughput_100_segments(benchmark_db, realistic_segments_100):
    """Measure throughput: 100 segments."""
    # Target: >20 segments/sec

@pytest.mark.benchmark
def test_throughput_500_segments(benchmark_db, realistic_segments_500):
    """Measure throughput: 500 segments (large filing)."""
    # Target: >15 segments/sec (some slowdown expected)

@pytest.mark.benchmark
def test_throughput_1000_segments(benchmark_db, realistic_segments_1000):
    """Measure throughput: 1000 segments (stress test)."""
    # Target: >10 segments/sec
```

**Metrics to collect:**
- Total elapsed time
- Segments per second
- Candidates generated per segment
- Success rate (segments processed without errors)

**Output format:**
```
Throughput (100 segments): 23.4 segments/sec
Candidates generated: 45
Success rate: 98%
```

**Validation:**
```bash
pytest tests/performance/test_candidate_generation_benchmark.py::test_throughput_100_segments -v -s
```

---

#### A1.3: Implement Latency Benchmark (1 hour)

**Tests to implement:**

```python
@pytest.mark.benchmark
def test_latency_percentiles(benchmark_db, realistic_segments_100):
    """Measure latency percentiles (p50, p95, p99) per segment."""
    # Target p95: <500ms per segment

@pytest.mark.benchmark
def test_latency_worst_case(benchmark_db, pathological_segments):
    """Measure worst-case latency (very long segments, many numbers)."""
    # Identify performance cliffs
```

**Metrics to collect:**
- p50 (median) latency per segment
- p95 latency per segment
- p99 latency per segment
- Max latency (worst segment)

**Validation:**
```bash
pytest tests/performance/test_candidate_generation_benchmark.py::test_latency_percentiles -v -s
```

---

#### A1.4: Implement Memory Benchmark (1 hour)

**Dependencies**: Install `memory_profiler`
```bash
pip install memory-profiler
```

**Tests to implement:**

```python
@pytest.mark.benchmark
def test_memory_usage_baseline(benchmark_db, realistic_segments_100):
    """Measure peak memory usage for typical workload."""
    # Target: <100MB peak usage
    # Use memory_profiler to track allocation

@pytest.mark.benchmark
def test_memory_growth_over_time(benchmark_db):
    """Test for memory leaks over multiple runs."""
    # Process 10 filings sequentially
    # Verify memory doesn't grow unbounded
```

**Validation:**
```bash
pytest tests/performance/test_candidate_generation_benchmark.py::test_memory_usage_baseline -v -s
```

---

#### A1.5: Document Baseline Results (30 min)

**File to create**: `docs/PERFORMANCE_BASELINE.md`

**Content:**
```markdown
# Performance Baseline - Candidate Generation

**Date**: 2025-12-11
**Hardware**: [Your system specs]
**Python**: 3.x
**Database**: PostgreSQL 15.x

## Throughput

| Segments | Time (sec) | Throughput (seg/sec) | Candidates | Success Rate |
|----------|------------|----------------------|------------|--------------|
| 100      | 4.2        | 23.8                 | 45         | 98%          |
| 500      | 28.5       | 17.5                 | 212        | 97%          |
| 1000     | 67.3       | 14.9                 | 438        | 96%          |

## Latency (per segment)

| Metric | Value (ms) |
|--------|------------|
| p50    | 35         |
| p95    | 420        |
| p99    | 890        |
| Max    | 1,240      |

## Memory

| Metric | Value (MB) |
|--------|------------|
| Peak   | 87         |
| Average| 62         |

## Bottlenecks Identified

1. Confidence scoring for segments with many numbers (>50)
2. Feature extraction for table segments
3. Database queries for learned rules

## Optimization Opportunities

1. Cache compiled regex patterns
2. Batch database queries
3. Optimize confidence scoring for high-number segments
```

**Validation**: Review baseline numbers, identify any unexpected results

---

### Task A2: Integration Test Coverage (P3) - 2-3 hours

#### A2.1: Add Full Pipeline Test (30 min)

**File**: `tests/integration/test_e2_candidate_filtering.py`

**Test to add:**

```python
def test_full_pipeline_with_real_filing(clean_db):
    """
    Test complete pipeline with realistic S-1 filing data.

    Verifies:
    - Candidates generated successfully
    - Confidence scores computed
    - False positives filtered
    - Learned rules applied (if present)
    - Results saved to database
    """
    # Use actual filing data from fixtures
    # Verify end-to-end flow
    # Check database state after processing
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py::test_full_pipeline_with_real_filing -v
```

---

#### A2.2: Add Error Recovery Tests (30 min)

**Tests to add:**

```python
def test_error_recovery_partial_failure(clean_db):
    """
    Test that generator continues after segment processing errors.

    Verifies:
    - Error in one segment doesn't stop processing
    - Other segments process successfully
    - Errors logged properly
    - Statistics reflect failures
    """

def test_malformed_segment_handling(clean_db):
    """
    Test handling of malformed segment data.

    Verifies:
    - Missing required fields handled gracefully
    - None values don't crash processing
    - Invalid data types caught early
    """
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py::test_error_recovery_partial_failure -v
```

---

#### A2.3: Add Deduplication Tests (30 min)

**Test to add:**

```python
def test_deduplication_across_segments(clean_db):
    """
    Test deduplication when same value appears in multiple segments.

    Verifies:
    - Same metric value in different segments detected
    - Only highest-confidence candidate kept
    - Deduplication logic correct
    - Statistics track duplicates found
    """
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py::test_deduplication_across_segments -v
```

---

#### A2.4: Add Performance Tests (30 min)

**Tests to add:**

```python
def test_performance_with_large_filing(clean_db):
    """
    Test performance with 500+ segments (realistic large filing).

    Verifies:
    - Completes in reasonable time (<30 seconds)
    - Memory usage stays bounded
    - No performance cliffs
    """

def test_performance_degradation_detection(clean_db):
    """
    Test that performance doesn't degrade with complex segments.

    Verifies:
    - Segments with many numbers (100+) process efficiently
    - Table segments don't cause slowdown
    - Confidence scoring scales linearly
    """
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py::test_performance_with_large_filing -v
```

---

#### A2.5: Add Learned Rules Tests (30 min)

**Tests to add:**

```python
def test_learned_rules_filtering_precision(clean_db):
    """
    Test E2 filtering maintains high precision.

    Verifies:
    - Learned patterns applied correctly
    - High-precision patterns filter effectively
    - Low-precision patterns not applied
    - Statistics track filtered candidates
    """

def test_learned_rules_database_integration(clean_db):
    """
    Test learned rules fetched from database correctly.

    Verifies:
    - Patterns loaded from DB
    - Only active patterns applied
    - Pattern matching logic correct
    - Performance acceptable (<100ms overhead)
    """
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py::test_learned_rules_filtering_precision -v
```

---

#### A2.6: Add Edge Case Tests (30 min)

**Tests to add:**

```python
def test_empty_segments_handling(clean_db):
    """Test handling of empty segments."""

def test_segments_with_no_numbers(clean_db):
    """Test segments with only text (no numbers)."""

def test_segments_with_no_keywords(clean_db):
    """Test segments with numbers but no metric keywords."""

def test_very_long_segments(clean_db):
    """Test segments >50KB (edge case)."""
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -k "edge_case" -v
```

---

### Workstream A: Deliverables Checklist

- [ ] `tests/performance/` directory created
- [ ] Performance benchmark tests implemented (5 tests)
- [ ] Baseline results documented in `docs/PERFORMANCE_BASELINE.md`
- [ ] Integration tests expanded (10+ new tests)
- [ ] All tests passing
- [ ] Branch ready for PR: `feature/test-infrastructure-improvements`

### Workstream A: Final Validation

```bash
# Run all performance benchmarks
pytest tests/performance/ -v -m benchmark -s

# Run all integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -v

# Verify coverage maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py --cov=src/review --cov-report=term-missing
```

---

## Workstream B: Source Code Quality (P1 → P4 → P5)

**Owner**: Developer B or Solo (sequential steps)
**Duration**: 5-7 hours (must be sequential)
**Branch**: `feature/source-code-improvements`
**Dependencies**: None - can start immediately

### Task B1: Configuration Centralization (P1) - 2-3 hours

#### B1.1: Create config.py Module (1 hour)

**File to create**: `src/review/config.py`

**Content:**

```python
"""
Configuration constants for the review module.

All tunable parameters for candidate generation, filtering,
scoring, and pattern analysis.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class CandidateGenerationConfig:
    """Configuration for candidate generation pipeline."""

    # ==================== Keyword Proximity ====================
    max_keyword_distance: int = 100
    """Maximum character distance between number and keyword."""

    # ==================== Context Extraction ====================
    context_words: int = 40
    """Number of words to extract in each direction around a position."""

    # ==================== False Positive Filtering ====================
    filter_false_positives: bool = True
    """Whether to apply false positive filtering."""

    min_metric_value: int = 10
    """Minimum numeric value to consider (filters single digits)."""

    filter_years: bool = True
    """Whether to filter year-like numbers (1990-2100)."""

    year_min: int = 1990
    """Earliest year to consider as false positive."""

    year_max: int = 2100
    """Latest year to consider as false positive."""

    filter_page_references: bool = True
    """Whether to filter page/section references."""

    filter_small_percentages: bool = True
    """Whether to filter small percentages (<1%)."""

    # ==================== Confidence Scoring ====================
    compute_confidence: bool = True
    """Whether to compute confidence scores for candidates."""

    confidence_weights: Optional[Dict[str, float]] = None
    """
    Weights for confidence scoring components.
    If None, uses default weights from METRIC_EXPECTED_FORMATS.
    """

    # ==================== E2 Pattern Filtering ====================
    apply_learned_rules: bool = True
    """Whether to apply learned patterns from human reviews."""

    min_pattern_precision: float = 0.75
    """Minimum precision for learned patterns to be applied."""

    # ==================== Performance Tuning ====================
    batch_size: int = 100
    """Batch size for database operations."""

    cache_word_positions: bool = True
    """Whether to cache word positions for context extraction (P1.2 optimization)."""

    def __post_init__(self):
        """Set default confidence weights if not provided."""
        if self.confidence_weights is None:
            # Import here to avoid circular dependency
            from src.review.confidence_scoring import METRIC_EXPECTED_FORMATS

            self.confidence_weights = {
                "keyword_proximity": 0.30,
                "definition_language": 0.20,
                "period_mentions": 0.15,
                "section_relevance": 0.15,
                "number_format_match": 0.10,
                "table_context": 0.10,
            }


# ==================== Global Default Config ====================
DEFAULT_CONFIG = CandidateGenerationConfig()
"""Default configuration used when no custom config is provided."""


# ==================== Configuration Presets ====================

def get_high_precision_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for high precision (fewer false positives).

    Use when you want to minimize review burden at cost of some recall.
    """
    return CandidateGenerationConfig(
        max_keyword_distance=50,  # Stricter proximity
        min_metric_value=100,  # Filter small numbers
        filter_false_positives=True,
        apply_learned_rules=True,
        min_pattern_precision=0.85,  # Higher precision threshold
    )


def get_high_recall_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for high recall (more candidates).

    Use when you want to catch all potential metrics at cost of more FPs.
    """
    return CandidateGenerationConfig(
        max_keyword_distance=150,  # Looser proximity
        min_metric_value=1,  # Keep all numbers
        filter_false_positives=False,  # No FP filtering
        apply_learned_rules=False,  # No learned filtering
    )


def get_fast_config() -> CandidateGenerationConfig:
    """
    Configuration optimized for speed.

    Use for quick prototyping or when performance matters more than quality.
    """
    return CandidateGenerationConfig(
        compute_confidence=False,  # Skip confidence computation
        apply_learned_rules=False,  # Skip pattern matching
        cache_word_positions=True,  # Enable caching
    )
```

**Validation:**
```python
from src.review.config import DEFAULT_CONFIG, get_high_precision_config

assert DEFAULT_CONFIG.max_keyword_distance == 100
assert get_high_precision_config().max_keyword_distance == 50
```

---

#### B1.2: Update candidate_generator.py (30 min)

**File**: `src/review/candidate_generator.py`

**Changes:**

1. Import config at top:
```python
from src.review.config import CandidateGenerationConfig, DEFAULT_CONFIG
```

2. Update `CandidateGenerator.__init__()`:
```python
class CandidateGenerator:
    """Generate review candidates from filing segments."""

    def __init__(
        self,
        config: Optional[CandidateGenerationConfig] = None,
        # Deprecated parameters (for backward compatibility)
        max_keyword_distance: Optional[int] = None,
        filter_false_positives: Optional[bool] = None,
        compute_confidence: Optional[bool] = None,
        apply_learned_rules: Optional[bool] = None,
    ):
        """
        Initialize candidate generator.

        Args:
            config: Configuration object. If None, uses DEFAULT_CONFIG.

            # Deprecated parameters (use config instead):
            max_keyword_distance: DEPRECATED - Use config.max_keyword_distance
            filter_false_positives: DEPRECATED - Use config.filter_false_positives
            compute_confidence: DEPRECATED - Use config.compute_confidence
            apply_learned_rules: DEPRECATED - Use config.apply_learned_rules
        """
        # Use provided config or default
        self.config = config or DEFAULT_CONFIG

        # Handle deprecated parameters (backward compatibility)
        if max_keyword_distance is not None:
            self.config.max_keyword_distance = max_keyword_distance
        if filter_false_positives is not None:
            self.config.filter_false_positives = filter_false_positives
        if compute_confidence is not None:
            self.config.compute_confidence = compute_confidence
        if apply_learned_rules is not None:
            self.config.apply_learned_rules = apply_learned_rules

        # Initialize components with config
        self.scorer = ConfidenceScorer() if self.config.compute_confidence else None
```

3. Replace all hardcoded constants with `self.config.*`:
```python
# BEFORE
MAX_KEYWORD_DISTANCE = 100

# AFTER
# Use self.config.max_keyword_distance instead
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_candidate_generator.py -v
```

---

#### B1.3: Update context_extraction.py (15 min)

**File**: `src/review/context_extraction.py`

**Changes:**

```python
# BEFORE
DEFAULT_CONTEXT_WORDS = 40

# AFTER
from src.review.config import DEFAULT_CONFIG

def extract_context_around_position(
    text: str,
    position: int,
    context_words: int = None,  # Make optional
    word_positions: Optional[List[Tuple[int, int]]] = None,
) -> str:
    """Extract context around a position."""
    if context_words is None:
        context_words = DEFAULT_CONFIG.context_words  # Use config default
    # ... rest of function
```

**Validation:**
```bash
pytest tests/unit/review/test_context_extraction.py -v
```

---

#### B1.4: Update false_positive_filter.py (15 min)

**File**: `src/review/false_positive_filter.py`

**Changes:**

```python
# BEFORE
YEAR_MIN = 1990
YEAR_MAX = 2100
MIN_METRIC_VALUE = 10

# AFTER
from src.review.config import DEFAULT_CONFIG

def is_false_positive(
    value: float,
    text_near_value: str,
    config: Optional[CandidateGenerationConfig] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a number is likely a false positive.

    Args:
        value: The numeric value
        text_near_value: Text context around the value
        config: Configuration (uses DEFAULT_CONFIG if None)
    """
    cfg = config or DEFAULT_CONFIG

    # Use cfg.year_min, cfg.year_max, cfg.min_metric_value, etc.
```

**Validation:**
```bash
pytest tests/unit/review/test_false_positive_filter.py -v
```

---

#### B1.5: Update confidence_scoring.py (15 min)

**File**: `src/review/confidence_scoring.py`

**Changes:**

```python
from src.review.config import DEFAULT_CONFIG

class ConfidenceScorer:
    """Compute confidence scores for review candidates."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        Initialize confidence scorer.

        Args:
            weights: Custom weights. If None, uses DEFAULT_CONFIG.confidence_weights.
        """
        self.weights = weights or DEFAULT_CONFIG.confidence_weights
```

**Validation:**
```bash
pytest tests/unit/review/test_confidence_scoring.py -v
```

---

#### B1.6: Update All Tests to Use Config (30 min)

**Files to update:**
- `tests/unit/review/test_candidate_generator.py`
- `tests/unit/review/test_context_extraction.py`
- `tests/unit/review/test_false_positive_filter.py`
- `tests/unit/review/test_confidence_scoring.py`

**Example test update:**

```python
# BEFORE
def test_custom_keyword_distance():
    generator = CandidateGenerator(max_keyword_distance=50)
    assert generator.config.max_keyword_distance == 50

# AFTER
from src.review.config import CandidateGenerationConfig

def test_custom_keyword_distance():
    config = CandidateGenerationConfig(max_keyword_distance=50)
    generator = CandidateGenerator(config=config)
    assert generator.config.max_keyword_distance == 50

def test_backward_compatibility_deprecated_params():
    """Verify deprecated parameters still work."""
    generator = CandidateGenerator(max_keyword_distance=50)
    assert generator.config.max_keyword_distance == 50
```

**Validation:**
```bash
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ -v
```

---

#### B1.7: Update Documentation (15 min)

**Files to update:**

1. `CLAUDE.md` - Add config section:
```markdown
## Review Module Configuration

The review system uses centralized configuration via `src/review/config.py`:

```python
from src.review.config import (
    DEFAULT_CONFIG,
    get_high_precision_config,
    get_high_recall_config,
    CandidateGenerationConfig,
)

# Use default configuration
generator = CandidateGenerator()

# Use preset configurations
generator = CandidateGenerator(config=get_high_precision_config())

# Custom configuration
config = CandidateGenerationConfig(
    max_keyword_distance=75,
    min_metric_value=50,
    apply_learned_rules=False,
)
generator = CandidateGenerator(config=config)
```

**Validation:**
- Review documentation for accuracy
- Ensure examples are correct

---

### Task B2: Type Hints Completeness (P4) - 1-2 hours

**Prerequisites**: P1 (B1) must be complete

#### B2.1: Install and Configure mypy (15 min)

**Add to `pyproject.toml`:**

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false  # Start permissive
check_untyped_defs = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_no_return = true
warn_unreachable = true
strict_optional = true

[[tool.mypy.overrides]]
module = "src.review.*"
disallow_untyped_defs = true  # Strict for review module
```

**Install mypy:**
```bash
pip install mypy
```

**Validation:**
```bash
mypy src/review/ --show-error-codes
```

---

#### B2.2: Add Type Hints to candidate_generator.py (30 min)

**Example fixes:**

```python
# BEFORE
def _process_segment(self, filing_id, company_id, segment, db=None):
    """Process a single segment."""
    # ...

# AFTER
def _process_segment(
    self,
    filing_id: int,
    company_id: int,
    segment: Dict[str, Any],
    db: Optional[DatabaseAdapter] = None,
) -> Tuple[List[ReviewCandidate], Dict[str, int]]:
    """
    Process a single segment to find candidates.

    Args:
        filing_id: The filing ID
        company_id: The company ID
        segment: Segment dict from database
        db: Optional DatabaseAdapter for learned rules filtering

    Returns:
        Tuple of (candidates, segment_stats)
    """
    # ...
```

**Run mypy after each method:**
```bash
mypy src/review/candidate_generator.py --show-error-codes
```

**Validation:**
```bash
# Should show no errors
mypy src/review/candidate_generator.py
```

---

#### B2.3: Add Type Hints to Other Modules (30 min)

**Files to update:**
- `src/review/confidence_scoring.py`
- `src/review/helpers.py`
- `src/review/context_extraction.py`
- `src/review/false_positive_filter.py`

**Process:**
1. Run mypy on each file
2. Add missing type hints
3. Use `# type: ignore[error-code]` for unavoidable Any usage
4. Re-run mypy to verify

**Validation:**
```bash
mypy src/review/ --strict
```

---

#### B2.4: Update Tests with Type Hints (15 min)

**Example:**

```python
# BEFORE
def test_generate_candidates():
    generator = CandidateGenerator()
    # ...

# AFTER
def test_generate_candidates() -> None:
    generator: CandidateGenerator = CandidateGenerator()
    # ...
```

**Validation:**
```bash
mypy tests/unit/review/ --strict
```

---

#### B2.5: Add mypy to CI (15 min)

**Create**: `.github/workflows/type-check.yml` (if using GitHub Actions)

```yaml
name: Type Check

on: [push, pull_request]

jobs:
  mypy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install mypy
      - run: mypy src/review/ --strict
```

**Validation:**
- Commit and push to trigger CI
- Verify mypy check passes

---

### Task B3: Documentation Examples (P5) - 2 hours

**Prerequisites**: P1 (B1) and P4 (B2) must be complete

#### B3.1: Add Examples to candidate_generator.py (30 min)

**Update module docstring:**

```python
"""
Candidate Generator - Generate review candidates from filing segments.

This module scans source segments for numbers near metric keywords,
creating candidates for human review. It implements a high-recall
detection strategy to catch potential metrics.

Basic Usage:
    >>> from src.review import CandidateGenerator
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> db = DatabaseAdapter(db_url)
    >>> generator = CandidateGenerator()
    >>>
    >>> # Generate candidates for a filing
    >>> segments = db.get_source_segments_for_filing(filing_id=123)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ...     db=db,
    ... )
    >>>
    >>> # Save to database
    >>> db.bulk_insert_review_candidates([c.to_dict() for c in candidates])

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Adjust keyword distance and disable FP filtering
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=False,
    ... )
    >>> generator = CandidateGenerator(config=config)

Configuration Presets:
    >>> from src.review.config import get_high_precision_config
    >>>
    >>> # Use high-precision preset
    >>> generator = CandidateGenerator(config=get_high_precision_config())

With Statistics:
    >>> candidates, stats = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ...     return_stats=True,
    ... )
    >>> print(f"Found {len(candidates)} candidates")
    >>> print(f"False positives filtered: {stats.false_positives_filtered}")
    >>> print(f"Success rate: {stats.segment_success_rate:.1%}")

See Also:
    - helpers.generate_candidates_for_filing() for convenience wrapper
    - confidence_scoring.ConfidenceScorer for scoring details
    - pattern_analyzer.PatternAnalyzer for learned patterns
"""
```

**Validation:**
- Read through examples for clarity
- Test examples in Python REPL

---

#### B3.2: Add Examples to confidence_scoring.py (20 min)

**Update module docstring:**

```python
"""
Confidence Scoring - Compute confidence scores for review candidates.

This module implements multi-signal confidence scoring based on:
- Keyword proximity (distance between number and metric keyword)
- Definition language (presence of "define", "represent", etc.)
- Period mentions (quarters, years, growth periods)
- Section relevance (non-risk-factor sections)
- Number format match (currency, percentage, integer expectations)
- Table context (metrics often appear in tables)

Basic Usage:
    >>> from src.review.confidence_scoring import ConfidenceScorer
    >>>
    >>> scorer = ConfidenceScorer()
    >>> score = scorer.compute_confidence(
    ...     keyword_distance=25,
    ...     has_definition_language=True,
    ...     in_table=False,
    ...     section_name="Business Overview",
    ...     number_format="currency",
    ...     metric_name="ARR",
    ... )
    >>> print(f"Confidence: {score:.2f}")  # 0.0-1.0

Custom Weights:
    >>> # Emphasize keyword proximity, de-emphasize table context
    >>> custom_weights = {
    ...     "keyword_proximity": 0.50,
    ...     "definition_language": 0.20,
    ...     "period_mentions": 0.15,
    ...     "section_relevance": 0.10,
    ...     "number_format_match": 0.05,
    ...     "table_context": 0.00,
    ... }
    >>> scorer = ConfidenceScorer(weights=custom_weights)

Using with CandidateGenerator:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Enable confidence scoring
    >>> config = CandidateGenerationConfig(compute_confidence=True)
    >>> generator = CandidateGenerator(config=config)
    >>>
    >>> # Candidates will have confidence_score populated
    >>> candidates = generator.generate_for_filing(...)
    >>> high_confidence = [c for c in candidates if c.confidence_score > 0.7]

See Also:
    - config.py for configuration options
    - METRIC_EXPECTED_FORMATS for format expectations per metric
"""
```

**Validation:**
- Test examples in Python REPL

---

#### B3.3: Add Examples to helpers.py (15 min)

**Update module docstring:**

```python
"""
Helpers - Convenience functions for candidate generation.

This module provides high-level convenience functions that handle
common workflows (database queries + candidate generation).

Basic Usage:
    >>> from src.review.helpers import generate_candidates_for_filing
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> db = DatabaseAdapter(db_url)
    >>>
    >>> # Generate candidates for a filing (one-liner)
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     company_id=456,
    ... )
    >>>
    >>> # Save to database
    >>> db.bulk_insert_review_candidates([c.to_dict() for c in candidates])

With Custom Configuration:
    >>> from src.review.config import get_high_precision_config
    >>>
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     company_id=456,
    ...     config=get_high_precision_config(),
    ... )

Batch Processing:
    >>> # Process multiple filings
    >>> filing_ids = [123, 456, 789]
    >>> for filing_id in filing_ids:
    ...     candidates = generate_candidates_for_filing(db, filing_id, company_id)
    ...     db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
    ...     print(f"Filing {filing_id}: {len(candidates)} candidates")

See Also:
    - candidate_generator.CandidateGenerator for lower-level API
    - config.py for configuration options
"""
```

---

#### B3.4: Add Examples to config.py (15 min)

**Update module docstring:**

```python
"""
Configuration - Centralized configuration for review module.

This module provides a single source of truth for all tunable parameters
in the candidate generation pipeline.

Basic Usage:
    >>> from src.review.config import DEFAULT_CONFIG
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Use default configuration
    >>> generator = CandidateGenerator()  # Uses DEFAULT_CONFIG
    >>> print(generator.config.max_keyword_distance)  # 100

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,
    ...     min_metric_value=100,
    ...     apply_learned_rules=False,
    ... )
    >>> generator = CandidateGenerator(config=config)

Configuration Presets:
    >>> from src.review.config import (
    ...     get_high_precision_config,
    ...     get_high_recall_config,
    ...     get_fast_config,
    ... )
    >>>
    >>> # Minimize false positives
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>>
    >>> # Maximize recall (catch all potential metrics)
    >>> hr_generator = CandidateGenerator(config=get_high_recall_config())
    >>>
    >>> # Optimize for speed
    >>> fast_generator = CandidateGenerator(config=get_fast_config())

Production Tuning:
    >>> # Start with defaults, then tune based on precision/recall metrics
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=75,  # Balanced
    ...     min_metric_value=50,      # Filter noise
    ...     apply_learned_rules=True, # Use patterns
    ...     min_pattern_precision=0.80, # High confidence patterns only
    ... )

See Also:
    - candidate_generator.CandidateGenerator for usage
    - CLAUDE.md for configuration guidelines
"""
```

---

#### B3.5: Update README.md or CLAUDE.md (30 min)

**Add "Quick Start" section to CLAUDE.md:**

```markdown
## Quick Start: Candidate Generation

### 1. Basic Usage

```python
from src.infra.db import DatabaseAdapter
from src.review import CandidateGenerator

# Initialize database and generator
db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
generator = CandidateGenerator()

# Generate candidates for a filing
segments = db.get_source_segments_for_filing(filing_id=123)
candidates = generator.generate_for_filing(
    filing_id=123,
    company_id=456,
    segments=segments,
    db=db,
)

# Save to database
db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
print(f"Generated {len(candidates)} candidates")
```

### 2. Using Configuration Presets

```python
from src.review.config import get_high_precision_config

# Use high-precision preset (fewer false positives)
config = get_high_precision_config()
generator = CandidateGenerator(config=config)
```

### 3. Custom Configuration

```python
from src.review.config import CandidateGenerationConfig

# Adjust parameters for your use case
config = CandidateGenerationConfig(
    max_keyword_distance=75,      # Moderate proximity
    min_metric_value=50,          # Filter small numbers
    apply_learned_rules=True,     # Use learned patterns
    min_pattern_precision=0.85,   # High-confidence patterns
)
generator = CandidateGenerator(config=config)
```

### 4. Convenience Wrapper

```python
from src.review.helpers import generate_candidates_for_filing

# One-liner for simple use cases
candidates = generate_candidates_for_filing(db, filing_id=123, company_id=456)
```
```

**Validation:**
- Review examples for accuracy
- Test examples work as written

---

### Workstream B: Deliverables Checklist

**P1: Configuration Centralization**
- [ ] `src/review/config.py` created
- [ ] All modules updated to use config
- [ ] Tests updated to use config
- [ ] Backward compatibility maintained
- [ ] Documentation updated

**P4: Type Hints**
- [ ] mypy installed and configured
- [ ] Type hints added to all modules
- [ ] Tests updated with type hints
- [ ] mypy CI job added
- [ ] All mypy checks passing

**P5: Documentation**
- [ ] Examples added to all module docstrings
- [ ] Quick start guide added to CLAUDE.md
- [ ] Examples tested and verified

### Workstream B: Final Validation

```bash
# Run all tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ -v --cov=src/review --cov-report=term-missing

# Run type checking
mypy src/review/ --strict

# Verify backward compatibility
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -v

# Check coverage maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/ --cov=src/review --cov-fail-under=98
```

---

## Coordination Points

### Branch Strategy

Both workstreams work on separate branches that can be merged independently:

```
main
├── feature/test-infrastructure-improvements (Workstream A)
│   ├── tests/performance/
│   └── tests/integration/ (expanded)
│
└── feature/source-code-improvements (Workstream B)
    ├── src/review/config.py (new)
    ├── src/review/*.py (updated with config, types, docs)
    └── tests/unit/review/ (updated)
```

**No merge conflicts expected** - branches touch completely different files.

### Merge Order

Either branch can merge first:

**Option 1: Workstream A first**
1. Merge `feature/test-infrastructure-improvements`
2. Merge `feature/source-code-improvements`
3. No conflicts (test files vs source files)

**Option 2: Workstream B first**
1. Merge `feature/source-code-improvements`
2. Merge `feature/test-infrastructure-improvements`
3. No conflicts

**Option 3: Simultaneous (preferred)**
1. Both branches ready for review
2. Review both PRs
3. Merge both (no conflicts)

### Communication Checkpoints

**Daily standup** (if working with team):
- What did you complete yesterday?
- What are you working on today?
- Any blockers?

**Mid-week sync** (Day 2):
- Workstream A: Performance baseline numbers available?
- Workstream B: Configuration module complete?
- Any issues discovered?

**End-of-week review** (Day 4):
- Both workstreams ready for PR?
- Final validation passing?
- Documentation complete?

---

## Success Criteria

### Workstream A (Test Infrastructure)

- [ ] 5+ performance benchmark tests passing
- [ ] Performance baseline documented with metrics
- [ ] 10+ new integration tests passing
- [ ] All integration tests cover edge cases
- [ ] Test coverage maintained at 98%+
- [ ] Branch ready for PR

### Workstream B (Source Code Quality)

- [ ] Configuration centralized in config.py
- [ ] All modules use config (no hardcoded constants)
- [ ] Backward compatibility maintained (0 breaking changes)
- [ ] Complete type hints (mypy --strict passing)
- [ ] Usage examples in all module docstrings
- [ ] Quick start guide in CLAUDE.md
- [ ] All tests passing (566+ tests)
- [ ] Test coverage maintained at 98%+
- [ ] Branch ready for PR

### Overall Success

- [ ] Both branches merged to main
- [ ] All 566+ tests passing
- [ ] Performance baseline established
- [ ] Configuration easily tunable
- [ ] Type safety enforced
- [ ] Documentation comprehensive
- [ ] Zero production issues
- [ ] Team confident in code quality

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Performance regression from refactor | Low | High | Benchmark before merge, compare baselines |
| Breaking changes from config refactor | Low | High | Maintain backward compatibility, deprecation warnings |
| Type hint conflicts with runtime | Low | Medium | Use type: ignore where needed, test thoroughly |
| Merge conflicts between branches | Very Low | Low | Branches touch different files |
| Time overrun | Medium | Medium | Focus on P1-P3 first, P4-P5 can slip |

---

## Timeline Summary

**Total Duration**: 4 days (with 2 parallel workstreams)

**Workstream A**: 5-7 hours
- Day 1-2: Performance benchmarking (3-4 hours)
- Day 2-3: Integration tests (2-3 hours)

**Workstream B**: 5-7 hours
- Day 1-2: Configuration centralization (2-3 hours)
- Day 3: Type hints (1-2 hours)
- Day 4: Documentation examples (2 hours)

**Both workstreams can run completely in parallel with zero dependencies.**

---

## Next Steps

1. **Create branches:**
   ```bash
   git checkout -b feature/test-infrastructure-improvements
   git checkout main
   git checkout -b feature/source-code-improvements
   ```

2. **Start Workstream A** (or assign to teammate):
   - Begin with `tests/performance/` setup
   - Run first benchmark to establish baseline

3. **Start Workstream B** (or work solo):
   - Create `src/review/config.py`
   - Update `candidate_generator.py`

4. **Daily progress tracking:**
   - Update this plan with completion checkmarks
   - Note any issues or deviations
   - Adjust timeline if needed

5. **End-of-week review:**
   - Create PRs for both branches
   - Review and merge
   - Celebrate successful parallel implementation! 🎉

# GPT-4 Code Review: D3 Code Quality

**Copy this entire prompt and paste into GPT-4**

---

You are a senior software engineer reviewing code quality of a Python SEC filing extraction system.

## Static Analysis Summary

**Codebase Size**: 39,847 LOC source, 81,244 LOC tests
**Test Coverage**: 81.57%
**mypy Errors**: 26 (mostly missing stubs)

### Top 10 Complexity Hotspots

| Rank | Function | CC | File |
|------|----------|-----|------|
| 1 | `_process_segment` | 57 | candidate_generator.py:481 |
| 2 | `find_keywords_near_number` | 46 | keyword_matching.py:523 |
| 3 | `bulk_insert_review_candidates` | 42 | db.py:1421 |
| 4 | `_generate_two_feature_patterns` | 38 | pattern_analyzer.py:1600 |
| 5 | `segment_filing` | 37 | html_segmenter.py:168 |
| 6 | `_validate_config` | 35 | keyword_config.py:82 |
| 7 | `_parse_table_row` | 34 | value_extractor.py:1179 |
| 8 | `is_false_positive` | 32 | false_positive_filter.py:722 |
| 9 | `_split_composite_segment` | 32 | html_segmenter.py:795 |
| 10 | `discover_patterns` | 31 | pattern_analyzer.py:939 |

**22 functions have CC > 20** (high complexity)
**113 functions have CC > 10** (moderate complexity)

### Maintainability Index (MI)

| File | LOC | MI Score | Rating |
|------|-----|----------|--------|
| db.py | 4,006 | 0.0 | Unmaintainable |
| html_segmenter.py | 2,028 | 0.0 | Unmaintainable |
| pattern_analyzer.py | 2,544 | 0.0 | Unmaintainable |
| segment_enricher.py | 1,878 | 15.99 | Low |
| value_extractor.py | 1,547 | 13.75 | Low |

### Type Safety Status

- `src/review/` - mypy --strict (enforced)
- `src/extraction/segment_enricher.py` - mypy --strict (enforced)
- Everything else - basic annotations only

### mypy Errors (26 total)

```
src/llm/prompts.py:77: error: Implicit Optional (context_text: str = None)
src/extraction/extraction_validation.py: 11 errors - List[None] violations
src/infra/sec_client.py:256: error: no-any-return
```

## Code Examples

### High Complexity Function (CC=57)
```python
def _process_segment(self, segment: Segment) -> List[ReviewCandidate]:
    # 400+ lines, 57 decision branches
    # Mix of:
    # - Number extraction
    # - Keyword matching
    # - Table row checking
    # - False positive filtering
    # - Context extraction
    # - Deduplication
    # - Confidence scoring
    # - Object creation
```

### Magic Numbers/Strings
```python
# Hardcoded thresholds scattered throughout:
MAX_KEYWORD_DISTANCE = 100  # chars
MIN_VALUE_THRESHOLD = 10
CONFIDENCE_THRESHOLD = 80  # percent
YEAR_RANGE = (1990, 2100)
TOC_PROXIMITY = 50  # chars
SEGMENT_LIMIT = 200  # for parallel processing
```

### Error Handling Pattern (inconsistent)
```python
# Some modules use exceptions:
raise ExtractionError(f"Failed to parse: {e}")

# Others use return codes:
if error:
    return None, "parse_failed"

# Others silently continue:
try:
    value = extract(text)
except:
    pass  # Ignore and continue
```

## Review Questions

1. **Complexity Decomposition**: How should CC=57 `_process_segment` be refactored?
2. **Type Safety Expansion**: Which modules should get mypy --strict next?
3. **Error Handling**: What's the right error handling strategy?
4. **Magic Values**: Should all thresholds be in config?
5. **Code Duplication**: Are there DRY violations?
6. **Documentation**: Are docstrings accurate?

## Output Format

```json
{
  "dimension": "D3_CODE_QUALITY",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D3-001",
      "severity": "Critical|High|Medium|Low",
      "category": "quality",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "code_before": "current problematic code",
      "code_after": "suggested improvement",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall code quality assessment"
}
```

Provide 10-15 findings focusing on maintainability and code health.


---

# ACTUAL SOURCE CODE

## src/review/candidate_generator.py (high complexity CC=57)

```python
"""
Candidate Generator - Generate review candidates from filing segments.

This module scans source segments for numbers near metric keywords,
creating candidates for human review. It implements a high-recall
detection strategy to catch potential metrics.

Algorithm:
1. For each segment, find all numbers using regex
2. For each number, find metric keywords within 100 characters
3. Deduplicate by (number_position, metric_id)
4. Extract context (30-50 words each direction)
5. Create ReviewCandidate objects for bulk insert

Basic Usage:
    >>> from src.review import CandidateGenerator
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> # Initialize with default config
    >>> db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
    >>> generator = CandidateGenerator()
    >>>
    >>> # Fetch segments for a filing
    >>> segments = db.get_source_segments_for_filing(filing_id=123)
    >>>
    >>> # Generate candidates
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ... )
    >>>
    >>> # Save to database
    >>> db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
    >>> print(f"Generated {len(candidates)} candidates")

Using Configuration Presets:
    >>> from src.review.config import (
    ...     get_high_precision_config,
    ...     get_high_recall_config,
    ...     get_fast_config,
    ... )
    >>>
    >>> # High precision: Fewer false positives, stricter matching
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>> hp_candidates = hp_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # High recall: Maximum coverage, more false positives
    >>> hr_generator = CandidateGenerator(config=get_high_recall_config())
    >>> hr_candidates = hr_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Fast: Optimized for speed, no confidence scoring
    >>> fast_generator = CandidateGenerator(config=get_fast_config())
    >>> fast_candidates = fast_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Create custom config for your use case
    >>> custom_config = CandidateGenerationConfig(
    ...     max_keyword_distance=75,        # Moderate proximity
    ...     min_metric_value=50,            # Filter small numbers
    ...     filter_false_positives=True,    # Enable filtering
    ...     compute_confidence=True,        # Enable confidence scoring
    ...     apply_learned_rules=True,       # Apply E2 patterns
    ...     min_pattern_precision=0.80,     # High-confidence patterns only
    ... )
    >>> custom_generator = CandidateGenerator(config=custom_config)
    >>> candidates = custom_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Getting Statistics:
    >>> # Request processing statistics
    >>> candidates, stats = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ...     return_stats=True,
    ... )
    >>> print(f"Segments processed: {stats.segments_processed}")
    >>> print(f"Numbers found: {stats.numbers_found}")
    >>> print(f"False positives filtered: {stats.false_positives_filtered}")
    >>> print(f"Candidates generated: {stats.candidates_generated}")
    >>> print(f"Success rate: {stats.segment_success_rate:.1%}")

Convenience Wrapper (Recommended for simple workflows):
    >>> from src.review.helpers import generate_candidates_for_filing
    >>>
    >>> # One-liner that fetches segments and generates candidates
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     company_id=456,
    ... )

Backward Compatibility (Old API still works):
    >>> # Old style: individual parameters
    >>> generator = CandidateGenerator(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_value=100,  # Old parameter name
    ... )
    >>>
    >>> # New style: config object (recommended)
    >>> from src.review.config import CandidateGenerationConfig
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_metric_value=100,  # New parameter name
    ... )
    >>> generator = CandidateGenerator(config=config)

See Also:
    - config.py: Configuration presets and CandidateGenerationConfig
    - helpers.py: Convenience wrappers for common workflows
    - models.py: ReviewCandidate and ProcessingStats data structures
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.review.marker_row_parser import MarkerRowParser
    from src.review.table_structure import TableRowParser

from src.review.confidence_scoring import ConfidenceScorer
from src.review.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONTEXT_WORDS,
    MAX_KEYWORD_DISTANCE,
    CandidateGenerationConfig,
)
from src.review.context_extraction import ContextExtractor
from src.review.deduplicator import deduplicate_candidates
from src.review.exceptions import (
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.false_positive_filter import (
    COUNT_ONLY_METRICS,
    DOLLAR_ONLY_METRICS,
    PERCENTAGE_ONLY_METRICS,
    FalsePositiveFilter,
    is_count_format,
    is_dollar_format,
    is_percentage_format,
    should_treat_as_percentage,
)
from src.review.feature_extractor import (
    FeatureExtractor,
)
from src.review.keyword_matching import (
    KeywordMatch,
    KeywordMatcher,
)
from src.review.models import (
    CandidateFeatures,
    ProcessingStats,
    ReviewCandidate,
    SegmentDict,
)
from src.review.number_parsing import NumberMatch, NumberParser

logger = logging.getLogger(__name__)


# =============================================================================
# Number Detection Patterns
# =============================================================================

# Number parsing functionality moved to src/review/number_parsing.py (P1.3)
# NUMBER_REGEX and NumberMatch are now imported from that module


# =============================================================================
# Metric Keywords (imported from keyword_matching.py)
# =============================================================================

# METRIC_KEYWORDS and SPECIFIC_KEYWORD_PATTERNS moved to
# src/review/keyword_matching.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Feature Detection Patterns (imported from feature_extractor)
# =============================================================================
# DEFINITION_PATTERNS, PERIOD_PATTERNS, and RISK_FACTORS_PATTERNS are now
# imported from src.review.feature_extractor to maintain single source of truth.


# =============================================================================
# False Positive Detection (imported from false_positive_filter.py)
# =============================================================================

# DATE_CONTEXT_PATTERNS, FALSE_POSITIVE_CONTEXT_PATTERNS, YEAR_MIN,
# YEAR_MAX, and MIN_METRIC_VALUE moved to src/review/false_positive_filter.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Configuration
# =============================================================================

# METRIC_EXPECTED_FORMATS moved to src/review/confidence_scoring.py
# ConfidenceScorer moved to src/review/confidence_scoring.py
# SPECIFIC_KEYWORD_PATTERNS moved to src/review/keyword_matching.py (P1.3)
# NumberMatch dataclass moved to src/review/number_parsing.py (P1.3)
# KeywordMatch dataclass moved to src/review/keyword_matching.py (P1.3)


# =============================================================================
# CandidateGenerator Class
# =============================================================================


class CandidateGenerator:
    """
    Generates review candidates from source segments.

    The generator scans text for numbers near metric keywords and creates
    ReviewCandidate objects for human review. It uses a high-recall strategy
    to avoid missing potential metrics.
    """

    # Maximum character distance between number and keyword
    # (imported from config.py for centralized configuration)
    MAX_KEYWORD_DISTANCE = MAX_KEYWORD_DISTANCE

    # Context extraction settings (imported from config.py)
    CONTEXT_WORDS = DEFAULT_CONTEXT_WORDS  # Words to extract each direction

    def __init__(
        self,
        config: CandidateGenerationConfig | None = None,
        # Deprecated parameters (for backward compatibility)
        max_keyword_distance: int | None = None,
        context_words: int | None = None,
        filter_false_positives: bool | None = None,
        min_value: int | None = None,
        filter_years: bool | None = None,
        compute_confidence: bool | None = None,
        apply_learned_rules: bool | None = None,
    ):
        """
        Initialize the candidate generator.

        Args:
            config: Configuration object. If None, uses DEFAULT_CONFIG or builds from deprecated params.

            # Deprecated parameters (use config instead):
            max_keyword_distance: DEPRECATED - Use config.max_keyword_distance
            context_words: DEPRECATED - Use config.context_words
            filter_false_positives: DEPRECATED - Use config.filter_false_positives
            min_value: DEPRECATED - Use config.min_metric_value
            filter_years: DEPRECATED - Use config.filter_years
            compute_confidence: DEPRECATED - Use config.compute_confidence
            apply_learned_rules: DEPRECATED - Use config.apply_learned_rules
        """
        # Handle config parameter vs deprecated individual parameters
        if config is not None:
            # Use provided config
            self.config = config
        elif any(
            param is not None
            for param in [
                max_keyword_distance,
                context_words,
                filter_false_positives,
                min_value,
                filter_years,
                compute_confidence,
                apply_learned_rules,
            ]
        ):
            # Build config from deprecated parameters (backward compatibility)
            self.config = CandidateGenerationConfig(
                max_keyword_distance=max_keyword_distance
                if max_keyword_distance is not None
                else DEFAULT_CONFIG.max_keyword_distance,
                context_words=context_words
                if context_words is not None
                else DEFAULT_CONFIG.context_words,
                filter_false_positives=filter_false_positives
                if filter_false_positives is not None
                else DEFAULT_CONFIG.filter_false_positives,
                min_metric_value=min_value
                if min_value is not None
                else DEFAULT_CONFIG.min_metric_value,
                filter_years=filter_years
                if filter_years is not None
                else DEFAULT_CONFIG.filter_years,
                compute_confidence=compute_confidence
                if compute_confidence is not None
                else DEFAULT_CONFIG.compute_confidence,
                apply_learned_rules=apply_learned_rules
                if apply_learned_rules is not None
                else DEFAULT_CONFIG.apply_learned_rules,
            )
        else:
            # Use default config
            self.config = DEFAULT_CONFIG

        # Set convenience attributes for backward compatibility
        self.max_keyword_distance = self.config.max_keyword_distance
        self.context_words = self.config.context_words
        self.filter_false_positives = self.config.filter_false_positives
        self.min_value = self.config.min_metric_value
        self.filter_years = self.config.filter_years
        self.compute_confidence = self.config.compute_confidence
        self.apply_learned_rules = self.config.apply_learned_rules

        # Initialize confidence scorer with config
        self._confidence_scorer = ConfidenceScorer(
            max_keyword_distance=self.config.max_keyword_distance,
            config=self.config,
        )

        # Initialize feature extractor
        self._feature_extractor = FeatureExtractor()

        # Initialize number parser (P1.3 - extracted to separate module)
        self._number_parser = NumberParser()

        # Initialize keyword matcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware, L4 multiplier)
        self._keyword_matcher = KeywordMatcher(
            max_keyword_distance=self.config.max_keyword_distance,
            prefer_closest_keyword=self.config.prefer_closest_keyword,
            respect_bullet_boundaries=self.config.respect_bullet_boundaries,
            respect_sentence_boundaries=self.config.respect_sentence_boundaries,
            log_ambiguous_matches=self.config.log_ambiguous_matches,
            ambiguity_threshold=self.config.ambiguity_threshold,
            post_value_distance_multiplier=self.config.post_value_distance_multiplier,
        )

        # Initialize false positive filter (P1.3 - extracted to separate module)
        self._false_positive_filter = FalsePositiveFilter(
            filter_enabled=self.config.filter_false_positives,
            min_value=self.config.min_metric_value,
            filter_years=self.config.filter_years,
            toc_proximity_chars=self.config.toc_proximity_chars,
            toc_dot_leader_window=self.config.toc_dot_leader_window,
            filter_financial_statements=self.config.filter_financial_statements,  # HRV-10/11
            financial_statement_proximity_chars=self.config.financial_statement_proximity_chars,
        )

        # Initialize context extractor (P1.3 - extracted to separate module)
        self._context_extractor = ContextExtractor(context_words=self.config.context_words)

        # Cache for word positions during segment processing (optimization for P1.2)
        # This avoids re-parsing text into words for every number in a segment
        self._current_segment_words: list[tuple[int, int, str]] | None = None

        # Lazy-loaded RuleApplicator (E2 integration)
        self._rule_applicator: Any | None = None

    def _get_rule_applicator(self, db: Any) -> Any | None:
        """
        Lazy-load RuleApplicator for E2 learned pattern filtering.

        Args:
            db: DatabaseAdapter instance (needed for pattern loading)

        Returns:
            RuleApplicator instance

        Note:
            Only loads RuleApplicator if apply_learned_rules=True.
            Caches the instance for reuse across segments.
        """
        if self._rule_applicator is None and self.apply_learned_rules:
            from src.review.rule_applicator import RuleApplicator

            self._rule_applicator = RuleApplicator(db)
        return self._rule_applicator

    def generate_for_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: list[SegmentDict],
        return_stats: bool = False,
        db: Any | None = None,
    ) -> list[ReviewCandidate] | tuple[list[ReviewCandidate], ProcessingStats]:
        """
        Generate candidates from all segments of a filing.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segments: List of segment dicts from database
            return_stats: If True, return (candidates, stats) tuple
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            List of ReviewCandidate objects (not yet saved to DB)
            If return_stats=True, returns tuple of (candidates, ProcessingStats)
        """
        candidates = []
        stats = ProcessingStats()

        for segment in segments:
            # Safely get segment_id for logging (segment might not be a dict)
            segment_id = (
                segment.get("source_segment_id")
                if isinstance(segment, dict)
                else None
            )
            try:
                segment_candidates, segment_stats = self._process_segment(
                    filing_id=filing_id,
                    company_id=company_id,
                    segment=segment,
                    db=db,
                )
                candidates.extend(segment_candidates)
                stats.segments_processed += 1
                stats.numbers_found += segment_stats.get("numbers_found", 0)
                stats.numbers_failed += segment_stats.get("numbers_failed", 0)
                stats.false_positives_filtered += segment_stats.get(
                    "false_positives_filtered", 0
                )
                stats.filtered_by_learned_rules += segment_stats.get(
                    "filtered_by_learned_rules", 0
                )
                stats.candidates_generated += len(segment_candidates)
            except SegmentProcessingError as e:
                # Known segment-level error (validation failures, etc.)
                stats.segments_failed += 1
                logger.error(
                    f"Segment processing error for segment {segment_id} in filing {filing_id}: {e}"
                )
                # Continue processing other segments
            except (ValueError, TypeError, AttributeError) as e:
                # Unexpected but recoverable error in segment processing
                stats.segments_failed += 1
                logger.error(
                    f"Unexpected error processing segment {segment_id} in filing {filing_id}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other segments

        # Deduplicate candidates across segments
        candidates, duplicates_removed = self._deduplicate_candidates(candidates)
        stats.duplicates_removed = duplicates_removed

        stats.log_summary(filing_id)

        if return_stats:
            return candidates, stats
        return candidates

    def _deduplicate_candidates(
        self, candidates: list[ReviewCandidate]
    ) -> tuple[list[ReviewCandidate], int]:
        """
        Remove duplicate candidates based on (parsed_value, suggested_metric_id, detected_period).

        Delegates to the standalone deduplicate_candidates function for reusability.
        P1.6: Passes prefer_same_sentence config setting for same-sentence preference.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            Tuple of (deduplicated_candidates, duplicates_removed_count)
        """
        return deduplicate_candidates(
            candidates,
            prefer_same_sentence=self.config.prefer_same_sentence_in_dedup,
        )

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: SegmentDict,
        db: Any | None = None,
    ) -> tuple[list[ReviewCandidate], dict[str, int]]:
        """
        Process a single segment to find candidates.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            Tuple of (candidates, segment_stats)
            segment_stats contains counts for numbers_found, numbers_failed,
            false_positives_filtered, filtered_by_learned_rules
        """
        segment_stats = {
            "numbers_found": 0,
            "numbers_failed": 0,
            "false_positives_filtered": 0,
            "filtered_by_learned_rules": 0,
        }

        # Validate segment dict
        if not isinstance(segment, dict):
            raise SegmentProcessingError(
                f"Segment must be a dict, got {type(segment).__name__}"
            )

        text = segment.get("raw_text", "")
        if not text:
            return [], segment_stats

        # Validate text is a string
        if not isinstance(text, str):
            raise SegmentProcessingError(
                f"raw_text must be a string, got {type(text).__name__}",
                segment_id=segment.get("source_segment_id"),
            )

        source_segment_id = segment.get("source_segment_id")

        # Skip definition segments - they explain metrics but don't contain values (EI-1)
        if segment.get("contains_definition_flag"):
            logger.debug(
                f"Skipping definition segment {source_segment_id}: "
                "contains_definition_flag is True"
            )
            return [], segment_stats

        candidates = []

        # Find all numbers in the segment
        numbers = self._find_numbers(text)
        if not numbers:
            return [], segment_stats

        segment_stats["numbers_found"] = len(numbers)

        # Pre-compute all keyword matches once for efficiency (P1.1 optimization)
        # This avoids re-searching the text for every number
        all_keywords = self._find_all_keywords(text)

        # Pre-compute word positions once for efficiency (P1.2 optimization)
        # This avoids re-parsing text for context extraction for every number
        self._current_segment_words = self._context_extractor.parse_text_into_words(text)

        # Pre-compute semantic boundaries once for efficiency (P1 enhancement)
        # This enables boundary-aware keyword matching to avoid cross-boundary false positives
        from src.review.boundary_detection import BoundaryDetector

        boundaries = None
        detector: BoundaryDetector | None = None
        if self.config.enable_boundary_detection:
            detector = BoundaryDetector()
            boundaries = detector.find_boundaries(text)
            logger.debug(f"Detected {len(boundaries)} semantic boundaries in segment")

        # Pre-compute sentence boundaries for P1.5 sentence-aware filtering
        # This enables sentence-aware keyword matching to avoid cross-sentence false positives
        sentence_boundaries = None
        if self.config.detect_sentences:
            if detector is None:  # Reuse detector if already created
                detector = BoundaryDetector()
            segment_type = segment.get("segment_type")
            # Disable sentence detection for tables (configurable)
            if segment_type == "table" and not self.config.sentence_detection_for_tables:
                # Table segments get single boundary to prevent false negatives
                pass  # sentence_boundaries stays None, fallback to no sentence filtering
            else:
                sentence_boundaries = detector.find_sentence_boundaries(text, segment_type)
                if sentence_boundaries:
                    logger.debug(
                        f"Detected {len(sentence_boundaries)} sentences in segment"
                    )

        # Pre-compute table row structure for table row filtering
        # This prevents keywords in one row from matching with numbers in another row
        table_row_parser: MarkerRowParser | TableRowParser | None = None
        raw_html = segment.get("raw_html", "")

        # Check for markers first (more reliable when present)
        if " [ROW] " in text or " [CELL] " in text:
            from src.review.marker_row_parser import MarkerRowParser
            table_row_parser = MarkerRowParser(text)
        elif raw_html and ('<table' in raw_html.lower()):
            from src.review.table_structure import TableRowParser
            table_row_parser = TableRowParser(raw_html, text)

        if table_row_parser is not None and table_row_parser.is_table():
            logger.debug(
                f"Parsed {len(table_row_parser.get_rows())} table rows for row-aware matching"
            )

        # Track (number_position, metric_id) pairs to avoid duplicates
        seen: set[tuple[int, str]] = set()

        # For each number, find nearby keywords
        for num in numbers:
            try:
                # Filter out likely false positives
                is_fp, fp_reason = self._is_likely_false_positive(text, num)
                if is_fp:
                    logger.debug(
                        f"Filtered false positive: {num.raw_text!r} ({fp_reason})"
                    )
                    segment_stats["false_positives_filtered"] += 1
                    continue

                keyword_matches = self._find_keywords_near_number(
                    num, all_keywords, boundaries, sentence_boundaries, segment, table_row_parser
                )

                # Phase 7: If no nearby keywords found, check context_prefix
                # Context prefix contains the last sentence from the previous segment,
                # which may provide relevant keyword context for list items, etc.
                context_prefix_raw = segment.get("context_prefix", "")
                context_prefix = str(context_prefix_raw) if context_prefix_raw else ""
                from_context_prefix = False
                if not keyword_matches and context_prefix:
                    # Search context_prefix for keywords
                    context_keywords = self._find_all_keywords(context_prefix)
                    if context_keywords:
                        # Use context keywords (they won't have "nearby" relationship to number)
                        # Take first keyword per metric for simplicity
                        seen_metrics: set[str] = set()
                        for ck in context_keywords:
                            if ck.metric_id not in seen_metrics:
                                keyword_matches.append(ck)
                                seen_metrics.add(ck.metric_id)
                        from_context_prefix = True
                        logger.debug(
                            f"Found {len(keyword_matches)} keywords in context_prefix "
                            f"for number {num.raw_text!r}"
                        )

                for kw in keyword_matches:
                    # Deduplicate by (number_position, metric_id)
                    key = (num.start, kw.metric_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Early exclusion check around NUMBER position
                    # This catches FPs where number is near exclusion context
                    # (e.g., contribution margin values matched to take rate)
                    # EXT-FN-1: Pass table_row_parser to limit exclusion context to same row
                    should_exclude, reason = self._keyword_matcher.should_exclude_for_number_context(
                        metric_id=kw.metric_id,
                        text=text,
                        number_position=num.start,
                        table_row_parser=table_row_parser,
                    )
                    if should_exclude:
                        segment_stats["excluded_by_number_context"] = (
                            segment_stats.get("excluded_by_number_context", 0) + 1
                        )
                        logger.debug(f"Excluded candidate: {reason}")
                        continue

                    # Calculate distance and position
                    # For context_prefix matches, use a special "large" distance
                    if from_context_prefix:
                        distance = 500  # Indicates "from context, not nearby"
                        keyword_position = "before"  # Context is from previous segment
                    else:
                        distance = self._calculate_distance(num, kw)
                        # L3: Use direction from KeywordMatch (handle "at" edge case by mapping to "before")
                        # Rationale: When keyword and number are at same position, treat as "before" (no penalty)
                        # since there's no temporal "after" relationship in reading order
                        keyword_position = "after" if kw.direction == "after" else "before"

                    # Extract context
                    context = self._extract_context(text, num.start)

                    # Compute ML features
                    features = self._compute_features(
                        number=num,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        context_text=context,
                        segment=segment,
                        all_numbers=numbers,
                    )

                    # L4/E1: Compute context type for multiplier optimization
                    context_type = self._keyword_matcher.get_context_type(
                        text=text,
                        number_position=num.start,
                        keyword_position=kw.start,
                        keyword_direction=kw.direction if kw.direction else keyword_position,
                        boundaries=boundaries,
                        segment_type=segment.get("segment_type"),
                    )
                    features.context_type = context_type

                    # P1.6: Track if keyword and number are in the same sentence
                    if sentence_boundaries and not from_context_prefix:
                        number_sentence = self._keyword_matcher._get_boundary_at_position(
                            num.start, sentence_boundaries
                        )
                        keyword_sentence = self._keyword_matcher._get_boundary_at_position(
                            kw.start, sentence_boundaries
                        )
                        features.is_same_sentence = (
                            number_sentence is not None
                            and keyword_sentence is not None
                            and number_sentence == keyword_sentence
                        )
                    elif from_context_prefix:
                        # Context prefix matches are never "same sentence" (different segments)
                        features.is_same_sentence = False
                    else:
                        # Without sentence detection, assume same sentence (conservative)
                        features.is_same_sentence = True

                    # Phase 7: Track if keyword came from context_prefix
                    features.from_context_prefix = from_context_prefix

                    # Compute confidence score
                    confidence = None
                    if self.compute_confidence:
                        confidence = self._confidence_scorer.compute_confidence(
                            keyword_distance=distance,
                            keyword_position=keyword_position,
                            keyword=kw.keyword,
                            metric_id=kw.metric_id,
                            features=features,
                        )

                        # Phase 7: Apply 0.8x confidence penalty for context_prefix matches
                        # These matches are less certain since keyword is in a different segment
                        if from_context_prefix and confidence is not None:
                            confidence = confidence * 0.8
                            logger.debug(
                                f"Applied 0.8x confidence penalty for context_prefix match: "
                                f"{confidence:.3f}"
                            )

                    candidate = ReviewCandidate(
                        filing_id=filing_id,
                        company_id=company_id,
                        source_segment_id=source_segment_id,
                        char_position=num.start,
                        context_text=context,
                        raw_number_text=num.raw_text,
                        parsed_value=num.value,
                        parsed_unit=num.unit,
                        triggering_keyword=kw.keyword,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        suggested_metric_id=kw.metric_id,
                        suggestion_confidence=confidence,
                        features=features,
                    )
                    candidates.append(candidate)

            except NumberProcessingError as e:
                # Known number-level error (already defined but not yet raised internally)
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Number processing error for {num.raw_text!r} at position {num.start}: {e}"
                )
                # Continue processing other numbers
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                # Unexpected but recoverable error in number processing
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Unexpected error processing number {num.raw_text!r} at position {num.start}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other numbers

        # Clear cached word positions (P1.2 optimization cleanup)
        self._current_segment_words = None

        # L1: Enrich with respectively patterns (before learned rules filtering)
        candidates = self._enrich_with_respectively_patterns(
            candidates=candidates,
            segment_text=text,
        )

        # E2: Apply learned pattern filtering if enabled
        if self.apply_learned_rules and db is not None:
            applicator = self._get_rule_applicator(db)
            if applicator is not None:
                filtered_candidates = []
                for candidate in candidates:
                    should_filter, reason = applicator.should_filter(
                        candidate, candidate.features
                    )
                    if should_filter:
                        segment_stats["filtered_by_learned_rules"] += 1
                        logger.debug(
                            f"Filtered candidate by learned rule: {reason} "
                            f"(value={candidate.parsed_value}, metric={candidate.suggested_metric_id})"
                        )
                    else:
                        filtered_candidates.append(candidate)
                candidates = filtered_candidates

        # HRV Type Validation: Filter candidates with wrong format for metric type
        if self.config.filter_false_positives:  # Reuse FP filter flag
            filtered_candidates = []
            for candidate in candidates:
                metric_id = candidate.suggested_metric_id
                raw_text = candidate.raw_number_text
                unit = candidate.parsed_unit or "count"
                context_text = candidate.context_text  # FIX-A: Get context for context-aware checks

                # Check if metric has type constraints
                type_mismatch = False
                mismatch_reason = None

                if metric_id in PERCENTAGE_ONLY_METRICS:
                    # FIX-A: Use context-aware percentage detection for retention metrics
                    if not should_treat_as_percentage(metric_id, raw_text, unit, context_text):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects percentage, got {unit}"

                elif metric_id in DOLLAR_ONLY_METRICS:
                    if not is_dollar_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects dollar amount, got {unit}"

                elif metric_id in COUNT_ONLY_METRICS:
                    if not is_count_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects count, got {unit}"

                if type_mismatch:
                    segment_stats["filtered_by_type_validation"] = segment_stats.get("filtered_by_type_validation", 0) + 1
                    logger.debug(
                        f"Filtered by type validation: {mismatch_reason} "
                        f"(value={candidate.parsed_value}, raw={raw_text})"
                    )
                else:
                    filtered_candidates.append(candidate)

            candidates = filtered_candidates

        return candidates, segment_stats

    def _find_numbers(self, text: str) -> list[NumberMatch]:
        """
        Find all numbers in text.

        Delegates to NumberParser (P1.3 - extracted to separate module).

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects
        """
        return self._number_parser.find_numbers(text)

    # _parse_number method removed - now part of NumberParser (P1.3)

    def _is_likely_false_positive(
        self, text: str, number: NumberMatch
    ) -> tuple[bool, str | None]:
        """
        Check if a number match is likely a false positive.

        Delegates to FalsePositiveFilter (P1.3 - extracted to separate module).

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        return self._false_positive_filter.is_false_positive(text, number)

    def _find_all_keywords(self, text: str) -> list[KeywordMatch]:
        """
        Find all metric keywords in text.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        return self._keyword_matcher.find_all_keywords(text)

    def _find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: list[KeywordMatch],
        boundaries: list[Any] | None = None,
        sentence_boundaries: list[Any] | None = None,
        segment: SegmentDict | None = None,
        table_row_parser: Any | None = None,
    ) -> list[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware).

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching (P1 enhancement)
            sentence_boundaries: Optional list of TextBoundary objects for sentence-aware matching (P1.5 enhancement)
            segment: Optional segment dict for context (L4 Option C)
            table_row_parser: Optional TableRowParser for table row filtering

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        # Extract text and segment_type for L4 Option C context detection
        text = segment.get("raw_text", "") if segment else ""
        segment_type = segment.get("segment_type") if segment else None

        return self._keyword_matcher.find_keywords_near_number(
            number,
            all_keywords,
            boundaries,
            sentence_boundaries,
            text=text,
            segment_type=segment_type,
            table_row_parser=table_row_parser,
        )

    def _calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self._keyword_matcher.calculate_distance(number, keyword)

    def _extract_context(self, text: str, position: int) -> str:
        """
        Extract context words around a position.

        Delegates to ContextExtractor (P1.3 - extracted to separate module).
        Uses cached word positions if available (optimization P1.2).

        Args:
            text: The full text
            position: Character position to center on

        Returns:
            Context string with ~context_words words each direction
        """
        return self._context_extractor.extract_context(
            text, position, cached_words=self._current_segment_words
        )

    def _compute_features(
        self,
        number: NumberMatch,
        keyword_distance: int,
        keyword_position: str,
        context_text: str,
        segment: SegmentDict,
        all_numbers: list[NumberMatch],
    ) -> CandidateFeatures:
        """
        Compute ML features for a candidate.

        Delegates to FeatureExtractor for feature computation.

        Args:
            number: The NumberMatch for this candidate
            keyword_distance: Distance to triggering keyword
            keyword_position: 'before' or 'after'
            context_text: Extracted context around number
            segment: Segment dict with metadata
            all_numbers: All numbers found in the segment

        Returns:
            CandidateFeatures instance
        """
        # Defensive: ensure segment is a dict
        if not isinstance(segment, dict):
            segment = {}  # type: ignore[unreachable]

        # Defensive: ensure all_numbers is a list
        if not isinstance(all_numbers, list):
            all_numbers = []  # type: ignore[unreachable]

        # Delegate to feature extractor
        return self._feature_extractor.compute_features(
            number_value=number.value,
            number_unit=number.unit,
            number_raw_text=number.raw_text,
            keyword_distance=keyword_distance,
            keyword_position=keyword_position,
            context_text=context_text,
            segment_type=segment.get("segment_type"),
            section_heading=segment.get("section_heading"),
            section_path=segment.get("section_path"),
            surrounding_numbers_count=max(0, len(all_numbers) - 1),
        )

    def _enrich_with_respectively_patterns(
        self,
        candidates: list[ReviewCandidate],
        segment_text: str,
    ) -> list[ReviewCandidate]:
        """
        Enrich candidates with period associations from respectively patterns (L1).

        Detects patterns like:
            "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."

        And enriches matching candidates with detected_period="2015" etc. in features.

        Args:
            candidates: Candidates generated from segment
            segment_text: Full segment text to search for patterns

        Returns:
            Enriched candidates with detected_period in features
        """
        # Skip if disabled
        if not self.config.detect_respectively_patterns:
            return candidates

        # L1-P1.2: Detect patterns (single or multiple depending on config)
        from src.review.respectively_parser import (
            detect_all_respectively_patterns,
            detect_respectively_pattern,
        )

        if self.config.detect_all_respectively_patterns:
            # Detect ALL patterns in segment
            patterns = detect_all_respectively_patterns(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
        else:
            # Backward compatible: detect only first pattern
            pattern = detect_respectively_pattern(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
            patterns = [pattern] if pattern else []

        # No patterns found
        if not patterns:
            return candidates

        # Build lookup: normalized value -> (period, confidence)
        # If multiple patterns have same value, use highest confidence
        value_to_period: dict[str, tuple[str, float]] = {}
        for pattern in patterns:
            for value_text, period_text in pattern.associations:
                normalized = self._normalize_value_text(value_text)

                # Keep highest confidence if duplicate
                if normalized in value_to_period:
                    existing_confidence = value_to_period[normalized][1]
                    if pattern.confidence > existing_confidence:
                        value_to_period[normalized] = (period_text, pattern.confidence)
                else:
                    value_to_period[normalized] = (period_text, pattern.confidence)

        # Enrich candidates
        enriched_count = 0
        for candidate in candidates:
            # Try to match candidate value to pattern value
            normalized_candidate = self._normalize_value_text(
                candidate.raw_number_text or ""
            )

            if normalized_candidate in value_to_period:
                period, confidence = value_to_period[normalized_candidate]

                # Update features
                if candidate.features:
                    candidate.features.detected_period = period
                    candidate.features.respectively_confidence = confidence
                    enriched_count += 1

        if enriched_count > 0:
            logger.info(
                f"Enriched {enriched_count}/{len(candidates)} candidates with "
                f"{len(patterns)} respectively pattern(s)"
            )

        return candidates

    def _normalize_value_text(self, value_text: str) -> str:
        """
        Normalize value text for matching (remove spaces, standardize units).

        L1-P1.3 Enhancement: Standardizes magnitude suffixes for consistent matching.

        Used to match candidate raw_number_text with respectively pattern values.
        Handles variations like "million" vs "M", "billion" vs "B", etc.

        Examples:
            "$1M" -> "$1m"
            "$ 1 M" -> "$1m"
            "$1 million" -> "$1m"
            "$1Million" -> "$1m"
            "33.0%" -> "33.0%"
            "1.42" -> "1.42"
            "10 thousand" -> "10k"
            "5bn" -> "5b"

        Args:
            value_text: Raw value text to normalize

        Returns:
            Normalized text for matching
        """
        # Remove spaces
        normalized = value_text.replace(" ", "")

        # Standardize magnitude suffixes (long form → short form, then lowercase)
        # Order matters: do long forms first to avoid partial replacements
        replacements = [
            ("million", "m"),
            ("Million", "m"),
            ("MILLION", "m"),
            ("billion", "b"),
            ("Billion", "b"),
            ("BILLION", "b"),
            ("thousand", "k"),
            ("Thousand", "k"),
            ("THOUSAND", "k"),
            ("mn", "m"),  # Alternate short form
            ("MN", "m"),
            ("Mn", "m"),
            ("bn", "b"),  # Alternate short form
            ("BN", "b"),
            ("Bn", "b"),
            ("M", "m"),  # Lowercase remaining
            ("B", "b"),
            ("K", "k"),
        ]

        for old, new in replacements:
            normalized = normalized.replace(old, new)

        return normalized


# =============================================================================
# Convenience Functions
# =============================================================================

# generate_candidates_for_filing() moved to src/review/helpers.py
```

## src/extraction/html_segmenter.py (first 600 lines)

```python
"""
HTML Segmenter - Parse filing HTML into semantic segments.

This module breaks down SEC filing HTML documents into atomic source segments
(paragraphs, tables, footnotes) that serve as the basis for metric extraction.
"""

import bisect
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.review.boundary_detection import BoundaryDetector

from .exceptions import EncodingError, HTMLParsingError, ValidationError
from .models import SourceSegment
from .validators import SegmentValidator

logger = logging.getLogger(__name__)

# Conditional import for charset-normalizer (graceful degradation)
try:
    from charset_normalizer import from_bytes
    CHARSET_NORMALIZER_AVAILABLE = True
except ImportError:
    CHARSET_NORMALIZER_AVAILABLE = False
    logger.warning(
        "charset-normalizer not available, using fallback encoding detection "
        "(UTF-8 → Latin-1 cascade)"
    )

# Minimum confidence threshold for auto-detection (0.0 to 1.0)
ENCODING_CONFIDENCE_THRESHOLD = 0.80

# Maximum bytes to read for encoding detection (64KB for large files)
ENCODING_DETECTION_MAX_BYTES = 65536


@dataclass
class SegmentationMetrics:
    """Metrics collected during HTML segmentation.

    Tracks performance, segment distribution, and warnings for observability.
    """

    filing_id: int
    total_segments: int = 0
    segment_counts_by_type: dict[str, int] = field(default_factory=dict)
    total_text_length: int = 0
    parse_time_seconds: float = 0.0
    encoding_used: str = "utf-8"
    warnings: list[str] = field(default_factory=list)

    def avg_segment_length(self) -> float:
        """Calculate average segment text length."""
        if self.total_segments == 0:
            return 0.0
        return self.total_text_length / self.total_segments

    def summary(self) -> str:
        """Generate human-readable summary."""
        type_counts = ", ".join(
            f"{count} {seg_type}s"
            for seg_type, count in sorted(self.segment_counts_by_type.items())
        )
        return (
            f"{self.total_segments} segments in {self.parse_time_seconds:.3f}s "
            f"({type_counts}, avg length: {self.avg_segment_length():.0f} chars)"
        )


class HTMLSegmenter:
    """
    Segment SEC filing HTML into source_segments for metric extraction.

    Segments types:
        - paragraph: Text paragraphs
        - table: HTML tables
        - footnote: Footnotes and endnotes
        - definition_block: Detected definition sections
        - methodology_block: Detected calculation methodology sections
        - other: Fallback for other content
    """

    # Minimum text length for a segment to be included
    MIN_SEGMENT_LENGTH = 50

    # Maximum text length for a single text segment
    MAX_SEGMENT_LENGTH = 10000

    # Maximum text length for tables (higher limit to preserve data integrity)
    TABLE_MAX_LENGTH = 25000

    # Parallel processing configuration (SEG11)
    PARALLEL_SENTENCE_DETECTION_WORKERS = 4
    PARALLEL_SENTENCE_DETECTION_THRESHOLD = 50

    # Patterns that indicate definition or methodology blocks
    DEFINITION_PATTERNS = [
        r"\b(we\s+define|defined\s+as|definition\s+of|refers\s+to)\b",
        r"\b(means|meaning|metric\s+definitions)\b",
    ]

    METHODOLOGY_PATTERNS = [
        r"\b(calculated\s+as|calculated\s+by|calculation|computed\s+as)\b",
        r"\b(determined\s+by|formula|methodology)\b",
    ]

    # Metadata headings to skip when determining section context
    # These are navigation/structural elements, not content sections
    METADATA_HEADINGS = frozenset(
        {
            "table of contents",
            "index",
            "cover page",
            "prospectus cover",
            "part of prospectus",
            "explanatory note",
            "forward-looking statements",
            "about this prospectus",
        }
    )

    # Definition start patterns - detect when a segment begins a definition
    # that may continue into subsequent segments
    DEFINITION_START_PATTERNS = [
        r"\bwe\s+define\s+['\"]?[\w\s]+['\"]?\s+as\b",  # "We define 'X' as..."
        r"\b['\"][\w\s]+['\"]?\s+(?:means|refers\s+to)\b",  # "'X' means..."
        r"\bdefined\s+as\b",  # "...defined as..."
        r"\bthe\s+following\s+(?:table|metrics?|terms?)\b",  # "the following metrics..."
    ]

    # Signals that a segment is a continuation of a previous definition
    DEFINITION_CONTINUATION_PATTERNS = [
        r"^[a-z]",  # Starts with lowercase (likely mid-sentence)
        r"^(?:and|or|but|which|that|who|where|when)\b",  # Starts with conjunction
        r"^\s*\(",  # Starts with parenthetical
        r"^(?:including|excluding|such\s+as)\b",  # Starts with qualifier
        r"^(?:Such|These|Those|This)\b",  # Demonstrative pronouns (SEG4)
        r"^The\s+(?:above|following)\b",  # Referential phrases (SEG4)
    ]

    # Limits for definition merging
    DEFINITION_LOOKAHEAD_MAX = 3  # Max segments to merge
    DEFINITION_MAX_COMBINED_LENGTH = 2000  # Max combined length

    def __init__(self, min_length: int = MIN_SEGMENT_LENGTH, max_length: int = MAX_SEGMENT_LENGTH):
        """
        Initialize the HTML segmenter.

        Args:
            min_length: Minimum text length for segments
            max_length: Maximum text length for segments
        """
        # Validate length parameters
        SegmentValidator.validate_min_max_length(min_length, max_length)
        self.min_length = min_length
        self.max_length = max_length
        self._metrics: SegmentationMetrics | None = None
        # SEG3: Singleton BoundaryDetector to reduce object allocation overhead
        self._boundary_detector = BoundaryDetector()

    def segment_filing(
        self, filing_id: int, html_path: str, raise_on_error: bool = False
    ) -> list[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Args:
            filing_id: Database filing ID
            html_path: Path to HTML file
            raise_on_error: If True, raise exceptions instead of returning empty list
                (default: False for backward compatibility)

        Returns:
            List of SourceSegment objects (not yet inserted to DB)

        Raises:
            ValidationError: If filing_id or html_path is invalid (only if raise_on_error=True)
            EncodingError: If file encoding cannot be determined (only if raise_on_error=True)
            HTMLParsingError: If HTML structure is invalid (only if raise_on_error=True)
        """
        start_time = time.time()

        # Validate inputs
        try:
            SegmentValidator.validate_filing_id(filing_id)
            validated_path = SegmentValidator.validate_html_path(html_path)
        except (ValidationError, FileNotFoundError, PermissionError) as e:
            if raise_on_error:
                raise
            logger.error(f"Validation failed for filing {filing_id}: {e}")
            return []

        logger.info(f"Segmenting filing {filing_id} from {html_path}")

        # Initialize metrics
        self._metrics = SegmentationMetrics(filing_id=filing_id)

        # Read HTML file with encoding detection
        try:
            html_content, encoding_used = self._read_html_file_with_encoding(str(validated_path))
            self._metrics.encoding_used = encoding_used
        except EncodingError as e:
            if raise_on_error:
                raise
            logger.error(f"Encoding error for filing {filing_id}: {e}")
            self._metrics.warnings.append(f"Encoding error: {e}")
            return []

        if not html_content:
            msg = f"Empty HTML content for filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=str(validated_path))
            logger.warning(msg)
            self._metrics.warnings.append("Empty HTML content")
            return []

        # Parse with BeautifulSoup
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            msg = f"Failed to parse HTML for filing {filing_id}: {e}"
            if raise_on_error:
                raise HTMLParsingError(
                    msg, filing_id=filing_id, html_path=str(validated_path)
                ) from e
            logger.error(msg)
            self._metrics.warnings.append(f"Parse error: {e}")
            return []

        # Find the main content area (usually in <BODY> or after <TEXT> tag)
        main_content = self._find_main_content(soup)
        if not main_content:
            msg = f"Could not find main content in filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=str(validated_path))
            logger.warning(msg)
            self._metrics.warnings.append("No main content found")
            return []

        # Pre-build heading cache for O(1) lookups (performance optimization)
        self._heading_cache = self._build_heading_cache(main_content)

        # Extract segments
        raw_segments = []
        sequence_index = 0

        # Cache elements by sequence index for composite splitting (SEG9 optimization)
        # This avoids redundant BeautifulSoup parsing in _split_composite_segment()
        # The cache is cleared after splitting to release DOM references
        element_cache: dict[int, Tag] = {}

        # Extract all segments
        for element in main_content.find_all(
            ["p", "table", "div", "ul", "ol", "blockquote", "pre", "figure"],
            recursive=True
        ):
            # Skip if element is nested inside a table (we'll capture the whole table)
            if element.name in ("p", "blockquote", "pre", "figure") and element.find_parent("table"):
                continue

            # Skip list items nested inside another list (we'll handle from outer list)
            if element.name in ["ul", "ol"] and element.find_parent(["ul", "ol"]):
                continue

            # Skip nested blockquote/figure inside same element type (extract outer only)
            if element.name == "blockquote" and element.find_parent("blockquote"):
                continue
            if element.name == "figure" and element.find_parent("figure"):
                continue

            # Skip div that only wraps a table with no additional text content
            # This prevents duplicate extraction - the inner table will be extracted separately
            # with correct type and [ROW]/[CELL] markers
            if element.name == "div":
                inner_table = element.find("table")
                if inner_table:
                    div_text = self._normalize_text(element.get_text())
                    table_text = self._normalize_text(inner_table.get_text())
                    if div_text == table_text:
                        # Div adds nothing beyond the table - skip it
                        continue

            # Skip elements nested in a div that contains BOTH text and tables (L5 composite splitting)
            # Those elements will be extracted when the parent div is split
            if element.name in ["p", "table"]:
                parent_div = element.find_parent("div")
                if parent_div:
                    # Check if the div has both paragraphs and tables (composite segment)
                    has_table = parent_div.find("table") is not None
                    has_paragraph = parent_div.find("p") is not None
                    if has_table and has_paragraph:
                        # This is a composite segment - skip nested elements
                        # They'll be handled when the div is split
                        continue

            # Handle lists specially - extract individual items with context (Phase 6)
            if element.name in ["ul", "ol"]:
                intro_text = self._get_list_intro_text(element)
                list_segments = self._extract_list_segments(
                    element, filing_id, sequence_index, intro_text
                )
                raw_segments.extend(list_segments)
                sequence_index += len(list_segments) if list_segments else 1
                continue

            segment = self._extract_segment(element, filing_id, sequence_index)
            if segment:
                raw_segments.append(segment)
                # Cache element for composite splitting (SEG9)
                element_cache[sequence_index] = element
                sequence_index += 1

        # Apply composite segment splitting (L5 enhancement)
        # This splits segments containing both text and tables into separate segments
        # Pass cached elements to avoid re-parsing HTML (SEG9 optimization)
        segments = []
        for segment in raw_segments:
            # Get cached element by integer sequence index
            cached_element = element_cache.get(int(segment.sequence_index))
            split_segs = self._split_composite_segment(segment, parsed_element=cached_element)
            segments.extend(split_segs)

        # Clear element cache - DOM elements no longer needed (SEG9 memory cleanup)
        # This releases references to the parsed DOM tree
        element_cache.clear()

        # Apply definition merging (Phase 3 of redesign)
        # This merges segments that split a definition across HTML elements
        segments = self._merge_definition_segments(segments)

        # Apply sentence detection (Phase 2 of redesign)
        # This stores sentence boundaries in segment metadata for:
        # - Preventing mid-sentence truncation
        # - Context overlap extraction
        # Use parallel processing for large filings (SEG11)
        if len(segments) >= self.PARALLEL_SENTENCE_DETECTION_THRESHOLD:
            segments = self._apply_sentence_detection_parallel(segments)
        else:
            for segment in segments:
                self._apply_sentence_detection(segment)

        # Handle large tables (Phase 4 of redesign)
        # Tables get a higher limit (25K) and summary generation if exceeded
        for i, segment in enumerate(segments):
            segments[i] = self._handle_large_table(segment)

        # Add context enrichment (Phase 5 of redesign)
        # This adds context overlap and document position
        segments = self._add_context_overlap(segments)
        segments = self._calculate_document_positions(segments)

        # Update metrics after splitting
        self._metrics.total_segments = len(segments)
        self._metrics.total_text_length = sum(len(s.raw_text) for s in segments)
        self._metrics.segment_counts_by_type = {}
        for segment in segments:
            seg_type = segment.segment_type
            self._metrics.segment_counts_by_type[seg_type] = (
                self._metrics.segment_counts_by_type.get(seg_type, 0) + 1
            )

        # Clear cache after processing
        self._heading_cache = None

        # Finalize metrics
        self._metrics.parse_time_seconds = time.time() - start_time

        # Enhanced logging
        logger.info(
            f"Extracted {len(segments)} segments from filing {filing_id}: {self._metrics.summary()}"
        )

        if self._metrics.warnings:
            logger.warning(
                f"Segmentation warnings for filing {filing_id}: {', '.join(self._metrics.warnings)}"
            )

        return segments

    def _read_html_file_with_encoding(self, html_path: str) -> tuple[str | None, str]:
        """Read HTML file with automatic encoding detection and fallback cascade.

        Detection order (SEG7):
        1. charset-normalizer auto-detection (if confidence >= 80%)
        2. UTF-8 explicit attempt
        3. Latin-1 fallback
        4. EncodingError (only if all above fail)

        Args:
            html_path: Path to HTML file

        Returns:
            Tuple of (content, encoding_used)

        Raises:
            EncodingError: If all encoding attempts fail
        """
        path = Path(html_path)
        attempted_encodings: list[str] = []

        # Step 1: Try auto-detection if charset-normalizer is available
        if CHARSET_NORMALIZER_AVAILABLE:
            detected_encoding = self._detect_encoding_auto(path)
            if detected_encoding:
                try:
                    content = path.read_text(encoding=detected_encoding)
                    logger.debug(
                        f"Successfully read {html_path} with auto-detected "
                        f"encoding: {detected_encoding}"
                    )
                    return (content, detected_encoding)
                except (UnicodeDecodeError, LookupError) as e:
                    attempted_encodings.append(detected_encoding)
                    logger.debug(
                        f"Auto-detected encoding {detected_encoding} failed for "
                        f"{html_path}: {e}. Falling back to explicit encodings."
                    )

        # Step 2: Try UTF-8 explicitly
        try:
            content = path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read {html_path} with UTF-8 encoding")
            return (content, "utf-8")
        except UnicodeDecodeError as e:
            if "utf-8" not in attempted_encodings:
                attempted_encodings.append("utf-8")
            position = e.start if hasattr(e, "start") else None
            logger.debug(
                f"UTF-8 decode failed for {html_path} at position {position}: {e}. "
                f"Trying latin-1 fallback..."
            )

        # Step 3: Fall back to latin-1
        try:
            content = path.read_text(encoding="latin-1")
            logger.info(
                f"Successfully read {html_path} with latin-1 encoding "
                f"(tried: {', '.join(attempted_encodings)})"
            )
            return (content, "latin-1")
        except UnicodeDecodeError as e:
            if "latin-1" not in attempted_encodings:
                attempted_encodings.append("latin-1")
            position = e.start if hasattr(e, "start") else None

            # Step 4: All encodings failed - raise EncodingError
            raise EncodingError(
                f"Failed to decode {html_path}. Attempted encodings: "
                f"{', '.join(attempted_encodings)}. File may have mixed or invalid encoding.",
                file_path=html_path,
                attempted_encodings=attempted_encodings,
                position=position,
            ) from e

    def _detect_encoding_auto(self, path: Path) -> str | None:
        """Detect file encoding using charset-normalizer library.

        Reads up to ENCODING_DETECTION_MAX_BYTES (64KB) for detection to handle
        large files efficiently.

        Args:
            path: Path to file

        Returns:
            Detected encoding name if confidence >= threshold, None otherwise
        """
        if not CHARSET_NORMALIZER_AVAILABLE:
            return None

        try:
            # Read file bytes (limited for large files)
            file_size = path.stat().st_size
            bytes_to_read = min(file_size, ENCODING_DETECTION_MAX_BYTES)

            with open(path, "rb") as f:
                raw_bytes = f.read(bytes_to_read)

            # Empty file - no detection needed
            if not raw_bytes:
                return None

            # Run charset detection
            result = from_bytes(raw_bytes)
            best_match = result.best()

            if best_match is None:
                logger.debug(f"charset-normalizer found no encoding match for {path}")
                return None

            encoding = best_match.encoding
            # charset-normalizer uses 0.0-1.0 for coherence, but we want confidence
            # The 'encoding' property returns the encoding, and we can check coherence
            # from the CharsetMatch object
            confidence = getattr(best_match, "coherence", 0.0)

            # Adjust threshold check - charset-normalizer's coherence is typically
            # high for valid text, but we use encoding_aliases for common aliases
            # Some encodings report as aliases (cp1252 = windows-1252)
            if confidence < ENCODING_CONFIDENCE_THRESHOLD:
                logger.debug(
                    f"Auto-detected {encoding} for {path} but confidence "
                    f"({confidence:.2f}) below threshold ({ENCODING_CONFIDENCE_THRESHOLD})"
                )
                return None

            logger.debug(
                f"Auto-detected encoding {encoding} for {path} "
                f"(confidence: {confidence:.2f})"
            )
            return encoding

        except Exception as e:
            # Any error in detection should not break the pipeline
            logger.debug(f"Encoding auto-detection failed for {path}: {e}")
            return None

    def _read_html_file(self, html_path: str) -> str | None:
        """DEPRECATED: Use _read_html_file_with_encoding() instead.

        Kept for backward compatibility with external callers.
        """
        try:
            content, _ = self._read_html_file_with_encoding(html_path)
            return content
        except EncodingError:
            return None

    def _find_main_content(self, soup: BeautifulSoup) -> Tag | None:
        """
        Find the main content area of the filing.

        SEC filings may have different structures:
        - SGML format: <DOCUMENT><TEXT><HTML>...</HTML></TEXT></DOCUMENT>
        - Modern HTML: <!DOCTYPE html><HTML>...</HTML>
        """
        # Try to find <TEXT> tag (SGML format) - case insensitive
        # Older filings may use uppercase <TEXT>, newer ones lowercase <text>
        text_tag = soup.find("text") or soup.find("TEXT")
        if text_tag:
            return text_tag

        # Fall back to <BODY> tag
        body_tag = soup.find("body")
        if body_tag:
            return body_tag

        # Last resort: use the whole soup
        return soup

    # =========================================================================
    # CSS Selector Generation Methods (SEG10)
    # =========================================================================

    def _element_selector(self, element: Tag) -> str:
        """
        Generate a CSS selector for a single element.

        Strategy:
        - If element has ID, use #id (most specific, globally unique)
        - If element has class(es), use tag.classname (first class only)
        - Otherwise use tag:nth-of-type(n) for uniqueness among siblings

        Args:
            element: BeautifulSoup Tag element

        Returns:
            CSS selector string for this element
        """
        tag = element.name

        # ID is most specific - use it alone
        element_id = element.get("id")
        if element_id:
            # Escape special CSS characters in ID
            escaped_id = self._escape_css_identifier(str(element_id))
            return f"#{escaped_id}"

        # Class adds specificity - use first class
        classes = element.get("class", [])
        if classes and isinstance(classes, list) and len(classes) > 0:
            # Use first class, escape if needed
            first_class = self._escape_css_identifier(str(classes[0]))
            return f"{tag}.{first_class}"

        # Fall back to nth-of-type for uniqueness among siblings
        # Count same-tag siblings before this element
        nth = 1
        if element.parent:
            for sibling in element.parent.children:
                if sibling is element:
                    break
                if hasattr(sibling, "name") and sibling.name == tag:
                    nth += 1
```

## src/extraction/keyword_config.py

```python
"""
Keyword Configuration Loader

Loads metric keyword patterns from external YAML configuration files,
allowing pattern updates without code changes.

Usage:
    from src.extraction.keyword_config import get_metric_keywords, get_exclusion_patterns

    # Get all keyword patterns
    keywords = get_metric_keywords()  # Returns dict[str, list[str]]

    # Get exclusion patterns
    exclusions = get_exclusion_patterns()  # Returns dict[str, list[str]]

    # Get specific patterns (for confidence bonuses)
    specific = get_specific_patterns()  # Returns list[str]
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

# Default config file location
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "metric_keywords.yaml"


class KeywordConfigError(Exception):
    """Raised when keyword configuration is invalid or cannot be loaded."""

    pass


@lru_cache(maxsize=1)
def _load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load and cache the keyword configuration from YAML.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Parsed YAML configuration dictionary.

    Raises:
        KeywordConfigError: If file cannot be loaded or parsed.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    # Allow override via environment variable
    env_path = os.environ.get("METRIC_KEYWORDS_CONFIG")
    if env_path:
        path = Path(env_path)

    if not path.exists():
        raise KeywordConfigError(f"Keyword config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise KeywordConfigError(f"Failed to parse keyword config: {e}") from e

    if not isinstance(config, dict):
        raise KeywordConfigError(f"Invalid config format: expected dict, got {type(config)}")

    # Validate structure
    _validate_config(config)

    logger.info(f"Loaded keyword config from {path}: {len(config)} metrics")
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """
    Validate the configuration structure.

    Args:
        config: Parsed YAML configuration.

    Raises:
        KeywordConfigError: If configuration is invalid.
    """
    for metric_id, metric_config in config.items():
        # Skip YAML anchor keys (starting with underscore)
        if metric_id.startswith("_"):
            continue

        if not isinstance(metric_config, dict):
            raise KeywordConfigError(
                f"Invalid config for {metric_id}: expected dict, got {type(metric_config)}"
            )

        if "patterns" not in metric_config:
            raise KeywordConfigError(f"Missing 'patterns' for metric {metric_id}")

        patterns = metric_config["patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise KeywordConfigError(
                f"Invalid 'patterns' for {metric_id}: expected non-empty list"
            )

        # Validate each pattern is a string
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, str):
                raise KeywordConfigError(
                    f"Invalid pattern {i} for {metric_id}: expected string, got {type(pattern)}"
                )

        # Validate exclusions if present
        if "exclusions" in metric_config:
            exclusions = metric_config["exclusions"]
            if not isinstance(exclusions, list):
                raise KeywordConfigError(
                    f"Invalid 'exclusions' for {metric_id}: expected list"
                )
            for i, exc in enumerate(exclusions):
                if not isinstance(exc, str):
                    raise KeywordConfigError(
                        f"Invalid exclusion {i} for {metric_id}: expected string"
                    )

        # Validate specific_patterns if present
        if "specific_patterns" in metric_config:
            specific = metric_config["specific_patterns"]
            if not isinstance(specific, list):
                raise KeywordConfigError(
                    f"Invalid 'specific_patterns' for {metric_id}: expected list"
                )

        # Validate required_context if present
        if "required_context" in metric_config:
            req_ctx = metric_config["required_context"]
            if not isinstance(req_ctx, dict):
                raise KeywordConfigError(
                    f"Invalid 'required_context' for {metric_id}: expected dict"
                )
            if "patterns" not in req_ctx:
                raise KeywordConfigError(
                    f"Missing 'patterns' in required_context for {metric_id}"
                )
            ctx_patterns = req_ctx["patterns"]
            if not isinstance(ctx_patterns, list) or not ctx_patterns:
                raise KeywordConfigError(
                    f"Invalid 'patterns' in required_context for {metric_id}: "
                    "expected non-empty list"
                )
            for j, ctx_pattern in enumerate(ctx_patterns):
                if not isinstance(ctx_pattern, str):
                    raise KeywordConfigError(
                        f"Invalid required_context pattern {j} for {metric_id}: "
                        "expected string"
                    )
            # Validate proximity_chars if present
            if "proximity_chars" in req_ctx:
                prox = req_ctx["proximity_chars"]
                if not isinstance(prox, int) or prox <= 0:
                    raise KeywordConfigError(
                        f"Invalid 'proximity_chars' in required_context for {metric_id}: "
                        "expected positive int"
                    )

        # Validate aliases if present
        if "aliases" in metric_config:
            aliases_list = metric_config["aliases"]
            if not isinstance(aliases_list, list):
                raise KeywordConfigError(
                    f"Invalid 'aliases' for {metric_id}: expected list"
                )
            for i, alias in enumerate(aliases_list):
                if not isinstance(alias, str):
                    raise KeywordConfigError(
                        f"Invalid alias {i} for {metric_id}: expected string"
                    )
                if not alias.startswith("cm_"):
                    raise KeywordConfigError(
                        f"Invalid alias '{alias}' for {metric_id}: must start with 'cm_'"
                    )

        # Validate status if present
        if "status" in metric_config:
            status = metric_config["status"]
            if not isinstance(status, str):
                raise KeywordConfigError(
                    f"Invalid 'status' for {metric_id}: expected string"
                )
            if status not in ("active", "deprecated"):
                raise KeywordConfigError(
                    f"Invalid 'status' value for {metric_id}: expected 'active' or 'deprecated'"
                )

        # Validate deprecation_reason if present
        if "deprecation_reason" in metric_config:
            reason = metric_config["deprecation_reason"]
            if not isinstance(reason, str):
                raise KeywordConfigError(
                    f"Invalid 'deprecation_reason' for {metric_id}: expected string"
                )


def _is_metric_key(key: str) -> bool:
    """Check if a key is a metric (not a YAML anchor starting with underscore)."""
    return not key.startswith("_")


def is_metric_deprecated(metric_id: str, config_path: str | None = None) -> bool:
    """
    Check if a metric is deprecated.

    Args:
        metric_id: The metric identifier to check.
        config_path: Optional path to config file.

    Returns:
        True if the metric has status='deprecated', False otherwise.
    """
    config = _load_config(config_path)
    metric_config = config.get(metric_id)
    if not metric_config:
        return False
    return metric_config.get("status") == "deprecated"


def get_active_metrics(config_path: str | None = None) -> list[str]:
    """
    Get all active (non-deprecated) metric IDs.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs that are not deprecated.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [
        metric_id
        for metric_id in config.keys()
        if _is_metric_key(metric_id) and config[metric_id].get("status") != "deprecated"
    ]


def get_metric_keywords(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get all metric keyword patterns.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of regex patterns.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    # Cast is safe: _validate_config() ensures patterns are list[str]
    return {
        metric_id: cast(list[str], metric_config["patterns"])
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id)
    }


def get_exclusion_patterns(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get exclusion patterns for metrics.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of exclusion regex patterns.
        Only includes metrics that have exclusions defined.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["exclusions"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "exclusions" in metric_config
    }


def get_specific_patterns(config_path: str | None = None) -> list[str]:
    """
    Get all specific (multi-word) patterns that get confidence bonuses.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of specific pattern strings (not compiled regex).
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    patterns: list[str] = []
    for metric_id, metric_config in config.items():
        if _is_metric_key(metric_id) and "specific_patterns" in metric_config:
            patterns.extend(metric_config["specific_patterns"])
    return patterns


def get_required_context(config_path: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Get required context patterns for metrics.

    Metrics with required_context only generate review candidates when
    at least one of the context patterns appears within proximity of the
    keyword match. This filters out revenue synonyms (GMV, TCV, etc.)
    that appear without cohort or per-customer context.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to required context configuration.
        Only includes metrics that have required_context defined.
        Each config contains:
        - 'patterns': list of regex patterns (at least one must match)
        - 'proximity_chars': max distance for context check (default: 1500)
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["required_context"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "required_context" in metric_config
    }


def reload_config() -> None:
    """
    Clear the cached configuration, forcing a reload on next access.

    Useful for testing or when the config file has been updated.
    """
    _load_config.cache_clear()
    logger.info("Keyword config cache cleared")


def get_metric_config(metric_id: str, config_path: str | None = None) -> dict[str, Any] | None:
    """
    Get the full configuration for a specific metric.

    Args:
        metric_id: The metric identifier (e.g., 'cm_customer_acquisition_cost').
        config_path: Optional path to config file.

    Returns:
        Dictionary with 'patterns', optional 'exclusions', and optional 'specific_patterns'.
        Returns None if metric not found.
    """
    config = _load_config(config_path)
    return config.get(metric_id)


def list_metrics(config_path: str | None = None) -> list[str]:
    """
    List all metric IDs defined in the configuration.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [k for k in config.keys() if _is_metric_key(k)]


# =============================================================================
# Metric ID Alias Functions
# =============================================================================


def get_aliases(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get aliases for metrics.

    Aliases allow a single canonical metric ID to match against alternative
    identifiers used in external sources (e.g., gold standard files).

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping canonical metric_id to list of alias IDs.
        Only includes metrics that have aliases defined.
        Excludes YAML anchor keys (starting with underscore).

    Example:
        >>> aliases = get_aliases()
        >>> aliases.get("cm_example_metric")
        ["cm_example_alias"]  # If defined in YAML
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["aliases"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "aliases" in metric_config
    }


def resolve_to_canonical(metric_id: str, config_path: str | None = None) -> str:
    """
    Resolve an alias to its canonical metric ID.

    If the input is already a canonical ID or not found in aliases,
    returns the input unchanged.

    Args:
        metric_id: The metric ID to resolve (may be canonical or alias).
        config_path: Optional path to config file.

    Returns:
        The canonical metric ID if input was an alias, otherwise the input.

    Example:
        >>> resolve_to_canonical("cm_example_alias")
        "cm_example_metric"  # If alias is defined

        >>> resolve_to_canonical("cm_arr")
        "cm_arr"  # No alias, returns unchanged
    """
    aliases = get_aliases(config_path)

    # Build reverse lookup: alias -> canonical
    alias_to_canonical: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            alias_to_canonical[alias] = canonical

    # Return canonical if found, otherwise return input
    return alias_to_canonical.get(metric_id, metric_id)


def get_all_equivalent_ids(metric_id: str, config_path: str | None = None) -> set[str]:
    """
    Get all equivalent metric IDs (canonical + aliases) for a given ID.

    Works whether input is canonical or alias.

    Args:
        metric_id: Any metric ID (canonical or alias).
        config_path: Optional path to config file.

    Returns:
        Set containing the canonical ID and all aliases.
        If metric has no aliases, returns set with just the input.

    Example:
        >>> get_all_equivalent_ids("cm_example_metric")
        {"cm_example_metric", "cm_example_alias"}  # If aliases defined

        >>> get_all_equivalent_ids("cm_arr")
        {"cm_arr"}  # No aliases, returns just the input
    """
    aliases = get_aliases(config_path)

    # First resolve to canonical
    canonical = resolve_to_canonical(metric_id, config_path)

    # Get all aliases for the canonical ID
    result = {canonical}
    if canonical in aliases:
        result.update(aliases[canonical])

    return result


def metrics_are_equivalent(
    metric_id_1: str, metric_id_2: str, config_path: str | None = None
) -> bool:
    """
    Check if two metric IDs are equivalent (same canonical or aliased).

    Args:
        metric_id_1: First metric ID.
        metric_id_2: Second metric ID.
        config_path: Optional path to config file.

    Returns:
        True if the metrics are equivalent (both resolve to same canonical).

    Example:
        >>> metrics_are_equivalent("cm_example_metric", "cm_example_alias")
        True  # If alias is defined

        >>> metrics_are_equivalent("cm_arr", "cm_mrr")
        False  # Different metrics
    """
    return (
        resolve_to_canonical(metric_id_1, config_path)
        == resolve_to_canonical(metric_id_2, config_path)
    )
```

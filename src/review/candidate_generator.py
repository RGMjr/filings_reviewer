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
    from src.review.boundary_detection import TextBoundary
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
    SegmentProcessingContext,
    SegmentStats,
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

    # =========================================================================
    # _process_segment helper methods (REV-07 refactoring)
    # =========================================================================

    def _validate_segment(self, segment: SegmentDict) -> str | None:
        """
        Validate segment and return text, or None if invalid/skippable.

        Args:
            segment: Segment dict from database

        Returns:
            The segment's raw_text if valid and processable, None otherwise.

        Raises:
            SegmentProcessingError: If segment structure is invalid
        """
        # Validate segment dict
        if not isinstance(segment, dict):
            raise SegmentProcessingError(
                f"Segment must be a dict, got {type(segment).__name__}"
            )

        text = segment.get("raw_text", "")
        if not text:
            return None

        # Validate text is a string
        if not isinstance(text, str):
            raise SegmentProcessingError(
                f"raw_text must be a string, got {type(text).__name__}",
                segment_id=segment.get("source_segment_id"),
            )

        # Skip definition segments that have no numeric disclosure (EI-1).
        # If a segment is both a definition AND contains a numeric disclosure, process it —
        # SEC filings commonly define a metric and report its value in the same paragraph.
        if segment.get("contains_definition_flag") and not segment.get(
            "contains_numeric_disclosure_flag"
        ):
            source_segment_id = segment.get("source_segment_id")
            logger.debug(
                f"Skipping definition segment {source_segment_id}: "
                "contains_definition_flag is True and no numeric disclosure"
            )
            return None

        return text

    def _prepare_context(
        self,
        text: str,
        segment: SegmentDict,
        filing_id: int,
        company_id: int,
    ) -> SegmentProcessingContext | None:
        """
        Pre-compute all segment-level data structures for processing.

        Args:
            text: The segment's raw text (already validated)
            segment: Segment dict from database
            filing_id: The filing ID
            company_id: The company ID

        Returns:
            SegmentProcessingContext with pre-computed data, or None if no numbers found
        """
        # Import boundary detector here to avoid circular import at module level
        from src.review.boundary_detection import BoundaryDetector

        source_segment_id = segment.get("source_segment_id")

        # Find all numbers in the segment
        numbers = self._find_numbers(text)
        if not numbers:
            return None

        # Pre-compute all keyword matches once for efficiency (P1.1 optimization)
        all_keywords = self._find_all_keywords(text)

        # Pre-compute word positions once for efficiency (P1.2 optimization)
        word_positions = self._context_extractor.parse_text_into_words(text)

        # Pre-compute semantic boundaries once for efficiency (P1 enhancement)
        boundaries: list[TextBoundary] | None = None
        detector: BoundaryDetector | None = None
        if self.config.enable_boundary_detection:
            detector = BoundaryDetector()
            boundaries = detector.find_boundaries(text)
            logger.debug(f"Detected {len(boundaries)} semantic boundaries in segment")

        # Pre-compute sentence boundaries for P1.5 sentence-aware filtering
        sentence_boundaries: list[TextBoundary] | None = None
        if self.config.detect_sentences:
            if detector is None:
                detector = BoundaryDetector()
            segment_type = segment.get("segment_type")
            # Disable sentence detection for tables (configurable)
            if segment_type == "table" and not self.config.sentence_detection_for_tables:
                pass  # sentence_boundaries stays None
            else:
                sentence_boundaries = detector.find_sentence_boundaries(text, segment_type)
                if sentence_boundaries:
                    logger.debug(
                        f"Detected {len(sentence_boundaries)} sentences in segment"
                    )

        # Pre-compute table row structure for table row filtering
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

        # Get context prefix (Phase 7)
        context_prefix_raw = segment.get("context_prefix", "")
        context_prefix = str(context_prefix_raw) if context_prefix_raw else ""

        # Store word positions for context extraction (P1.2 optimization)
        self._current_segment_words = word_positions

        return SegmentProcessingContext(
            text=text,
            source_segment_id=source_segment_id,
            filing_id=filing_id,
            company_id=company_id,
            segment=segment,
            numbers=tuple(numbers),
            all_keywords=tuple(all_keywords),
            word_positions=tuple(word_positions) if word_positions else None,
            boundaries=tuple(boundaries) if boundaries else None,
            sentence_boundaries=tuple(sentence_boundaries) if sentence_boundaries else None,
            table_row_parser=table_row_parser,
            context_prefix=context_prefix,
            segment_type=segment.get("segment_type"),
        )

    def _process_numbers(
        self,
        ctx: SegmentProcessingContext,
        stats: SegmentStats,
    ) -> list[ReviewCandidate]:
        """
        Main loop: process each number to generate candidates.

        Args:
            ctx: Pre-computed processing context
            stats: Mutable stats tracker

        Returns:
            List of candidates generated from all numbers
        """
        candidates: list[ReviewCandidate] = []
        seen: set[tuple[int, str]] = set()  # Track (number_position, metric_id)

        for num in ctx.numbers:
            try:
                num_candidates = self._process_one_number(num, ctx, seen, stats)
                candidates.extend(num_candidates)
            except NumberProcessingError as e:
                stats.inc("numbers_failed")
                logger.warning(
                    f"Number processing error for {num.raw_text!r} at position {num.start}: {e}"
                )
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                stats.inc("numbers_failed")
                logger.warning(
                    f"Unexpected error processing number {num.raw_text!r} at position {num.start}: "
                    f"{type(e).__name__}: {e}"
                )

        return candidates

    def _process_one_number(
        self,
        number: NumberMatch,
        ctx: SegmentProcessingContext,
        seen: set[tuple[int, str]],
        stats: SegmentStats,
    ) -> list[ReviewCandidate]:
        """
        Process single number: filter, match keywords, create candidates.

        Args:
            number: The number match to process
            ctx: Pre-computed processing context
            seen: Set of (position, metric_id) pairs already processed (mutated)
            stats: Mutable stats tracker (mutated)

        Returns:
            List of candidates generated for this number
        """
        candidates: list[ReviewCandidate] = []

        # Filter out likely false positives
        is_fp, fp_reason = self._is_likely_false_positive(ctx.text, number)
        if is_fp:
            logger.debug(f"Filtered false positive: {number.raw_text!r} ({fp_reason})")
            stats.inc("false_positives_filtered")
            return candidates

        # Find nearby keywords
        keyword_matches = self._find_keywords_near_number(
            number,
            list(ctx.all_keywords),
            list(ctx.boundaries) if ctx.boundaries else None,
            list(ctx.sentence_boundaries) if ctx.sentence_boundaries else None,
            ctx.segment,
            ctx.table_row_parser,
        )

        # Phase 7: If no nearby keywords found, check context_prefix
        from_context_prefix = False
        if not keyword_matches and ctx.context_prefix:
            context_keywords = self._find_all_keywords(ctx.context_prefix)
            if context_keywords:
                seen_metrics: set[str] = set()
                for ck in context_keywords:
                    if ck.metric_id not in seen_metrics:
                        keyword_matches.append(ck)
                        seen_metrics.add(ck.metric_id)
                from_context_prefix = True
                logger.debug(
                    f"Found {len(keyword_matches)} keywords in context_prefix "
                    f"for number {number.raw_text!r}"
                )

        # Create candidates for each keyword match
        for kw in keyword_matches:
            candidate = self._create_candidate(
                number=number,
                keyword=kw,
                ctx=ctx,
                seen=seen,
                stats=stats,
                from_context_prefix=from_context_prefix,
            )
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def _create_candidate(
        self,
        number: NumberMatch,
        keyword: KeywordMatch,
        ctx: SegmentProcessingContext,
        seen: set[tuple[int, str]],
        stats: SegmentStats,
        from_context_prefix: bool,
    ) -> ReviewCandidate | None:
        """
        Create single candidate from number-keyword pair.

        Args:
            number: The number match
            keyword: The keyword match
            ctx: Pre-computed processing context
            seen: Set of (position, metric_id) pairs already processed (mutated)
            stats: Mutable stats tracker (mutated)
            from_context_prefix: Whether keyword came from context_prefix

        Returns:
            ReviewCandidate if created, None if filtered/deduplicated
        """
        # Deduplicate by (number_position, metric_id)
        key = (number.start, keyword.metric_id)
        if key in seen:
            return None
        seen.add(key)

        # Early exclusion check around NUMBER position
        should_exclude, reason = self._keyword_matcher.should_exclude_for_number_context(
            metric_id=keyword.metric_id,
            text=ctx.text,
            number_position=number.start,
            table_row_parser=ctx.table_row_parser,
        )
        if should_exclude:
            stats.inc("excluded_by_number_context")
            logger.debug(f"Excluded candidate: {reason}")
            return None

        # Calculate distance and position
        if from_context_prefix:
            distance = 500  # Indicates "from context, not nearby"
            keyword_position = "before"  # Context is from previous segment
        else:
            distance = self._calculate_distance(number, keyword)
            keyword_position = "after" if keyword.direction == "after" else "before"

        # Extract context
        context = self._extract_context(ctx.text, number.start)

        # Compute ML features
        features = self._compute_features(
            number=number,
            keyword_distance=distance,
            keyword_position=keyword_position,
            context_text=context,
            segment=ctx.segment,
            all_numbers=list(ctx.numbers),
        )

        # L4/E1: Compute context type for multiplier optimization
        context_type = self._keyword_matcher.get_context_type(
            text=ctx.text,
            number_position=number.start,
            keyword_position=keyword.start,
            keyword_direction=keyword.direction if keyword.direction else keyword_position,
            boundaries=list(ctx.boundaries) if ctx.boundaries else None,
            segment_type=ctx.segment_type,
        )
        features.context_type = context_type

        # P1.6: Track if keyword and number are in the same sentence
        if ctx.sentence_boundaries and not from_context_prefix:
            number_sentence = self._keyword_matcher._get_boundary_at_position(
                number.start, list(ctx.sentence_boundaries)
            )
            keyword_sentence = self._keyword_matcher._get_boundary_at_position(
                keyword.start, list(ctx.sentence_boundaries)
            )
            features.is_same_sentence = (
                number_sentence is not None
                and keyword_sentence is not None
                and number_sentence == keyword_sentence
            )
        elif from_context_prefix:
            features.is_same_sentence = False
        else:
            features.is_same_sentence = True

        # Phase 7: Track if keyword came from context_prefix
        features.from_context_prefix = from_context_prefix

        # Compute confidence score
        confidence = None
        if self.compute_confidence:
            confidence = self._confidence_scorer.compute_confidence(
                keyword_distance=distance,
                keyword_position=keyword_position,
                keyword=keyword.keyword,
                metric_id=keyword.metric_id,
                features=features,
            )

            # Phase 7: Apply 0.8x confidence penalty for context_prefix matches
            if from_context_prefix and confidence is not None:
                confidence = confidence * 0.8
                logger.debug(
                    f"Applied 0.8x confidence penalty for context_prefix match: "
                    f"{confidence:.3f}"
                )

        return ReviewCandidate(
            filing_id=ctx.filing_id,
            company_id=ctx.company_id,
            source_segment_id=ctx.source_segment_id,
            char_position=number.start,
            context_text=context,
            raw_number_text=number.raw_text,
            parsed_value=number.value,
            parsed_unit=number.unit,
            triggering_keyword=keyword.keyword,
            keyword_distance=distance,
            keyword_position=keyword_position,
            suggested_metric_id=keyword.metric_id,
            suggestion_confidence=confidence,
            features=features,
        )

    def _check_metric_specific_fp(self, candidate: ReviewCandidate) -> str | None:
        """Check metric-specific false positive rules.

        Runs after type validation in _post_process_candidates. Returns a reason
        string if the candidate should be filtered, None to keep it.
        """
        import re as _re

        metric_id = candidate.suggested_metric_id
        context_text = candidate.context_text or ""
        raw_text = candidate.raw_number_text or ""
        value = candidate.parsed_value

        # --- ARR tier threshold ---
        # Block cm_arr when the value is a common tier boundary (e.g. $5K, $100K, $1M)
        # AND the context contains tier/threshold language.
        # Ported from V2 _rule_arr_tier_threshold.
        _ARR_TIER_VALUES = frozenset({
            5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 5_000_000,
        })
        _ARR_TIER_SOURCE_RE = _re.compile(
            r"""
            (?:
                \$\s*\d[\d,]*\s*(?:K|k|M|m)?\s*(?:or\s+more\s+)?(?:in\s+)?(?:ARR|arr)  # "$5K ARR", "$5K or more in ARR"
                |
                (?:ARR|arr)\s+of\s+\$                                                     # "ARR of $100,000"
                |
                (?:over|greater\s+than|more\s+than|above|exceeding|>)\s*\$                # "over $X"
                |
                (?:at\s+least|minimum)\s+\$                                               # "at least $X"
                |
                annualized\s+(?:recurring\s+)?revenue\s+(?:of\s+)?\$                     # "annualized revenue of $X"
            )
            """,
            _re.IGNORECASE | _re.VERBOSE,
        )
        if metric_id == "cm_arr" and value is not None:
            try:
                float_val = float(value)
            except (TypeError, ValueError):
                float_val = None
            if float_val is not None and float_val in _ARR_TIER_VALUES:
                if _ARR_TIER_SOURCE_RE.search(context_text):
                    return "arr_tier_threshold"

        # --- ARR magnitude cap ---
        # No real company has >$100B ARR; large values are TAM or financial figures.
        _ARR_MAX = 100_000_000_000  # $100B
        if metric_id == "cm_arr" and value is not None:
            try:
                float_val = float(value)
            except (TypeError, ValueError):
                float_val = None
            if float_val is not None and float_val > _ARR_MAX:
                return "arr_magnitude_cap"

        # --- TAM / market-size context ---
        # Block cm_arr when context discusses total addressable market or market size,
        # not actual company ARR.
        _TAM_RE = _re.compile(
            r"\b(?:total\s+addressable\s+market|TAM|market\s+(?:size|opportunity)|"
            r"addressable\s+(?:market|opportunity)|serviceable\s+(?:addressable|"
            r"obtainable|available))\b",
            _re.IGNORECASE,
        )
        if metric_id == "cm_arr" and _TAM_RE.search(context_text):
            return "arr_tam_context"

        # --- ARR: average ARR per customer is not total company ARR ---
        # "average ARR of our enterprise customers" (Datadog $140K) describes a per-customer
        # average, not the company's total ARR.
        if metric_id == "cm_arr" and _re.search(
            r"\baverage\s+(?:ARR|annual\s+recurring\b)", context_text, _re.IGNORECASE
        ):
            return "arr_average_not_total"

        # --- ARR: capital raised is not ARR ---
        # "we have raised $92.0 million of capital, net of share repurchases" (Datadog).
        if metric_id == "cm_arr" and _re.search(
            r"\bnet\s+of\s+share\s+repurchases?\b", context_text, _re.IGNORECASE
        ):
            return "arr_capital_not_arr"

        # --- Financial statement values on count-only customer metrics ---
        # Income-statement values (operating expenses, interest income, net loss)
        # occasionally land near a "customer" keyword in a distant section heading.
        # Guard: only suppress when the keyword is far (distance > 50 chars), to
        # avoid filtering legitimate customer metrics that appear near financial text.
        #
        # Uses a strict keyword set that excludes bare "revenue"/"revenues" to
        # avoid false matches on ARR discussions ("annual recurring revenue").
        _COUNT_CUSTOMER_METRICS = frozenset({
            "cm_active_customers_total",
            "cm_customers_period_end",
        })
        _STRICT_FIN_KEYWORDS = (
            "operating expenses", "operating income", "operating loss",
            "loss from operations", "income from operations",
            "interest income", "interest expense", "interest income (expense)",
            "net loss", "net income", "net earnings",
            "cost of revenue", "cost of sales", "cost of goods sold",
            "total revenue", "gross profit", "earnings per share",
            "sales and marketing", "general and administrative",
            "research and development",
        )
        if (
            metric_id in _COUNT_CUSTOMER_METRICS
            and candidate.keyword_distance is not None
            and candidate.keyword_distance > 50
        ):
            context_lower = context_text.lower()
            if any(kw in context_lower for kw in _STRICT_FIN_KEYWORDS):
                return "financial_context_on_customer_count"

        # --- CAC: percentage values are not dollar costs ---
        # Customer acquisition cost is a dollar amount, never a percentage.
        # Suppress % candidates that land near "cost to acquire" language (Robinhood "60%").
        if metric_id == "cm_customer_acquisition_cost" and "%" in raw_text:
            return "cac_percentage_not_cost"

        # --- New customer acquisition: stock inventory context ---
        # Stock reward programs hold a share inventory; the position size (e.g. 5,000)
        # is a stock holding count, not a new-customer acquisition count (Robinhood).
        if metric_id == "cm_new_customers_acquired":
            _STOCK_INVENTORY_RE = _re.compile(
                r"\b(?:settled\s+)?shares?\s+(?:held|of\s+stock|inventory)\b"
                r"|\bstock\s+of\s+issuers?\b"
                r"|\binventory\s+of\s+(?:settled\s+)?shares?\b",
                _re.IGNORECASE,
            )
            if _STOCK_INVENTORY_RE.search(context_text):
                return "stock_inventory_not_new_customers"

        # --- Feature-subset user/customer counts ---
        # Product/feature-qualified subsets (e.g. "Gold customers", "crypto users",
        # "Newsfeed users", "Watchlist users") are not total customer counts.
        # Uses context_text (40-word window) rather than the narrower YAML exclusion
        # window (±100 chars) to capture cases where the qualifier is farther away.
        _FEATURE_SUBSET_RE = _re.compile(
            r"\b(?:gold|premium|crypto)\s+(?:customers?|users?|subscribers?)\b"
            r"|\b(?:newsfeeds?|watchlists?|cash\s+management)\s+(?:users?|customers?)\b"
            r"|\bdebit\s+card\s+holders?\b"           # Cash Management debit card holders
            r"|\bfractional\s+(?:shares?|trades?)\b"  # Fractional share traders
            r"|\brobinhood\s+gold\b"                  # Robinhood Gold subscription service
            r"|\bnewsfeed\b",                         # Newsfeeds feature users
            _re.IGNORECASE,
        )
        if metric_id in _COUNT_CUSTOMER_METRICS and _FEATURE_SUBSET_RE.search(context_text):
            return "feature_subset_user_count"

        # --- Crypto trading customers are a product subset, not total customers ---
        # "over 16.4 million customers trade ... of cryptocurrency on our platform" (Robinhood)
        # is crypto feature users, not total customer count.
        if (
            metric_id in _COUNT_CUSTOMER_METRICS
            and _re.search(r"\bcryptocurrenc", context_text, _re.IGNORECASE)
            and _re.search(r"\btrad(?:e[sd]?|ing)\b", context_text, _re.IGNORECASE)
        ):
            return "feature_subset_user_count"

        # --- Margin product users are not total customer counts ---
        # "0.1 million users" / "0.3 million users" in margin receivables context (Robinhood)
        # describes margin borrowers, not total customers.
        if metric_id in _COUNT_CUSTOMER_METRICS and _re.search(
            r"\bmargin\s+(?:borrowers?|receivables?)\b", context_text, _re.IGNORECASE
        ):
            return "margin_product_not_total_customers"

        # --- Demographic age range / survey data at very large keyword distance ---
        # "young adults aged 18 to 29" in a Pew Research survey (Robinhood) are ages,
        # not customer counts; suppress when keyword is extremely distant.
        if (
            metric_id in _COUNT_CUSTOMER_METRICS
            and candidate.keyword_distance is not None
            and candidate.keyword_distance >= 400
            and _re.search(
                r"\b(?:pew\s+research|gallup\s+poll|survey)\b|\baged?\s+\d+\b",
                context_text,
                _re.IGNORECASE,
            )
        ):
            return "demographic_survey_not_customer_count"

        # --- Third-party case study customer counts ---
        # Vendor case studies (e.g. Datadog's Coinbase/Zendesk case studies) describe
        # customer companies' own metrics. "Customer Since: YYYY" is a case study header.
        if metric_id in _COUNT_CUSTOMER_METRICS and _re.search(
            r"\bCustomer\s+Since:\s*\d{4}\b", context_text, _re.IGNORECASE
        ):
            return "third_party_case_study"

        # --- Large customer count: employee headcount threshold is not a count ---
        # "enterprise customers, defined as having 5,000 or more employees" (Datadog)
        # is an employee count definition of the tier, not a count of large customers.
        if metric_id == "cm_large_customers_period_end" and _re.search(
            r"\b\d[\d,]*\s+or\s+more\s+employees?\b", context_text, _re.IGNORECASE
        ):
            return "employee_threshold_not_customer_count"

        # --- Revenue concentration: growth multiples are not concentration percentages ---
        # "a multiple of 4.0x" / "median multiple of 33.9x" (Datadog) are expansion
        # multiples, not revenue concentration ratios.
        if metric_id == "cm_revenue_concentration":
            # "a multiple of 4.0x" / "median multiple of 33.9x" are expansion multiples.
            # Require both "multiple" word and "Nx" notation to avoid over-firing on contexts
            # that happen to contain "x" (e.g. "10x surge in traffic").
            if (
                _re.search(r"\bmultiple\b", context_text, _re.IGNORECASE)
                and _re.search(r"\b\d+\.?\d*x\b", context_text, _re.IGNORECASE)
            ):
                return "revenue_concentration_growth_multiple"
            # "ARR from our top 25 customers" — the N in "top N customers" is a tier count,
            # not a percentage of revenue concentrated in those customers.
            # Only suppress when the extracted raw value IS the N (e.g. "25" in "top 25"),
            # not when the context merely mentions "top N" near a different value (e.g. "14%").
            raw_stripped = raw_text.strip().rstrip("%").rstrip("x").strip()
            if raw_stripped and _re.search(
                rf"\btop\s+{_re.escape(raw_stripped)}\s+customers?\b",
                context_text,
                _re.IGNORECASE,
            ):
                return "revenue_concentration_tier_count"

        # --- Net revenue retention: HTML style attribute values ---
        # HTML remnants like <p style="margin-top:12pt"> can appear in context_text.
        # Real NRR values always include "%" in their raw text (e.g. "146%").
        # A bare integer with no % sign in an NRR slot whose context has HTML style
        # attributes is an HTML parsing artifact (e.g. "12" from margin-top:12pt).
        if (
            metric_id == "cm_net_revenue_retention"
            and "%" not in raw_text
            and _re.search(r"style\s*=|margin-top:|margin-bottom:", context_text, _re.IGNORECASE)
        ):
            return "net_revenue_retention_html_artifact"

        # --- Volunteer/nonprofit context for customer-value metrics ---
        # Volunteer counts (e.g. "2,300 team members volunteer") near LTV/repeat-purchase
        # keywords are employee engagement stats, not customer-value metrics (Chewy).
        _VOLUNTEER_METRICS = frozenset({
            "cm_lifetime_value_per_customer",
            "cm_repeat_purchase_rate",
        })
        if metric_id in _VOLUNTEER_METRICS and "volunteer" in context_text.lower():
            return "volunteer_nonprofit_context"

        return None

    def _post_process_candidates(
        self,
        candidates: list[ReviewCandidate],
        text: str,
        db: Any | None,
        stats: SegmentStats,
    ) -> list[ReviewCandidate]:
        """
        Apply post-generation filters to candidates.

        Args:
            candidates: List of candidates to post-process
            text: Segment text (for respectively patterns)
            db: Optional DatabaseAdapter for learned rules filtering
            stats: Mutable stats tracker (mutated)

        Returns:
            Filtered list of candidates
        """
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
                        stats.inc("filtered_by_learned_rules")
                        logger.debug(
                            f"Filtered candidate by learned rule: {reason} "
                            f"(value={candidate.parsed_value}, metric={candidate.suggested_metric_id})"
                        )
                    else:
                        filtered_candidates.append(candidate)
                candidates = filtered_candidates

        # HRV Type Validation: Filter candidates with wrong format for metric type
        if self.config.filter_false_positives:
            filtered_candidates = []
            for candidate in candidates:
                metric_id = candidate.suggested_metric_id
                raw_text = candidate.raw_number_text
                unit = candidate.parsed_unit or "count"
                context_text = candidate.context_text

                # Check if metric has type constraints
                type_mismatch = False
                mismatch_reason = None

                if metric_id in PERCENTAGE_ONLY_METRICS:
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
                    stats.inc("filtered_by_type_validation")
                    logger.debug(
                        f"Filtered by type validation: {mismatch_reason} "
                        f"(value={candidate.parsed_value}, raw={raw_text})"
                    )
                else:
                    filtered_candidates.append(candidate)

            candidates = filtered_candidates

        # MFP: Metric-specific FP rules (post type validation)
        if self.config.filter_false_positives:
            filtered_candidates = []
            for candidate in candidates:
                fp_reason = self._check_metric_specific_fp(candidate)
                if fp_reason:
                    stats.inc("filtered_by_metric_fp_rule")
                    logger.debug(
                        f"Filtered by metric FP rule: {fp_reason} "
                        f"(value={candidate.parsed_value}, metric={candidate.suggested_metric_id})"
                    )
                else:
                    filtered_candidates.append(candidate)
            candidates = filtered_candidates

        return candidates

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: SegmentDict,
        db: Any | None = None,
    ) -> tuple[list[ReviewCandidate], dict[str, int]]:
        """
        Process a single segment to find candidates.

        Orchestrates the segment processing pipeline:
        1. Validate segment structure
        2. Prepare processing context (pre-compute data structures)
        3. Process each number to find keyword matches
        4. Post-process candidates (enrich, filter)

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            Tuple of (candidates, segment_stats dict for backward compatibility)
        """
        stats = SegmentStats()

        # Phase 1: Validate segment
        text = self._validate_segment(segment)
        if text is None:
            return [], stats.to_dict()

        # Phase 2: Prepare context (pre-compute all data structures)
        ctx = self._prepare_context(text, segment, filing_id, company_id)
        if ctx is None:
            return [], stats.to_dict()
        stats.numbers_found = len(ctx.numbers)

        # Phase 3: Process numbers to generate candidates
        candidates = self._process_numbers(ctx, stats)

        # Phase 4: Post-process candidates (enrich, filter)
        candidates = self._post_process_candidates(candidates, text, db, stats)

        # Cleanup cached word positions (P1.2 optimization)
        self._current_segment_words = None

        return candidates, stats.to_dict()

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
